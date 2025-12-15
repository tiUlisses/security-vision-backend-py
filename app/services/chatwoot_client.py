# app/services/chatwoot_client.py
from __future__ import annotations

from typing import Optional, Any
import asyncio
import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.models.incident import Incident
from app.models.incident_message import IncidentMessage

logger = logging.getLogger(__name__)


class ChatwootHTTPError(RuntimeError):
    """Erro HTTP do Chatwoot com status e corpo para tratamento robusto."""

    def __init__(
        self,
        *,
        status_code: int,
        method: str,
        path: str,
        url: str,
        body_text: str = "",
    ) -> None:
        super().__init__(f"Chatwoot HTTP error {status_code} for {method} {path}")
        self.status_code = status_code
        self.method = method
        self.path = path
        self.url = url
        self.body_text = body_text or ""


class ChatwootClient:
    """
    Cliente de integração com Chatwoot (best-effort: loga erro e não quebra fluxo).

    - Usa feature flag (CHATWOOT_ENABLED).
    - Cria/usa contact "sistema" (default_contact_identifier).
    - Cria/usa conversation por incidente (source_id = incident-{id}).
    - Resolve inbox do grupo (SupportGroup.chatwoot_inbox_identifier) ou default.
    - Envia notas privadas e, quando for mídia, tenta enviar como attachment.
    """

    def __init__(self) -> None:
        self.enabled = bool(settings.CHATWOOT_ENABLED)

        raw_base = settings.CHATWOOT_BASE_URL
        self.base_url = str(raw_base).rstrip("/") if raw_base else ""

        # Header já usado no projeto
        self.token = settings.CHATWOOT_API_ACCESS_TOKEN
        self.account_id = settings.CHATWOOT_DEFAULT_ACCOUNT_ID

        self.default_inbox_identifier = settings.CHATWOOT_DEFAULT_INBOX_IDENTIFIER
        self.default_contact_identifier = settings.CHATWOOT_DEFAULT_CONTACT_IDENTIFIER

        raw_incident_base = settings.CHATWOOT_INCIDENT_BASE_URL
        self.incident_base_url = str(raw_incident_base).rstrip("/") if raw_incident_base else None

        self._inbox_cache: dict[str, int] = {}
        self._contact_cache: dict[str, int] = {}

        self._http: Optional[httpx.AsyncClient] = None

    # ------------------------------ lifecycle / config

    def is_configured(self) -> bool:
        return bool(
            self.enabled
            and self.base_url
            and self.token
            and self.account_id
            and self.default_inbox_identifier
        )

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            # Mantém um client reaproveitável (evita overhead e melhora performance)
            self._http = httpx.AsyncClient(timeout=20.0)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _headers(self) -> dict[str, str]:
        return {"api_access_token": self.token or ""}

    def _set_incident_conversation_id(self, incident: Incident, conversation_id: int) -> None:
        """
        Ajuda MUITO em fluxos que criam várias mensagens seguidas:
        evita que send_incident_timeline_message dispare send_incident_notification repetidas vezes.
        """
        try:
            setattr(incident, "chatwoot_conversation_id", int(conversation_id))
        except Exception:
            # best effort
            pass

    # ------------------------------ request helper (com retry leve)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        files: Any | None = None,
        retries: int = 2,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        merged_headers = {**self._headers(), **(headers or {})}

        last_exc: Optional[Exception] = None

        for attempt in range(retries + 1):
            try:
                resp = await self._get_http().request(
                    method,
                    url,
                    headers=merged_headers,
                    json=json,
                    params=params,
                    files=files,
                )

                if resp.status_code >= 400:
                    body_text = resp.text or ""
                    logger.warning(
                        "[chatwoot] HTTP %s %s falhou: %s %s",
                        method,
                        url,
                        resp.status_code,
                        body_text[:2000],
                    )

                    if resp.status_code in (429, 502, 503, 504) and attempt < retries:
                        await asyncio.sleep(0.6 * (2**attempt))
                        continue

                    raise ChatwootHTTPError(
                        status_code=resp.status_code,
                        method=method,
                        path=path,
                        url=url,
                        body_text=body_text,
                    )

                try:
                    return resp.json()
                except ValueError:
                    return {}

            except Exception as e:
                last_exc = e
                if attempt < retries:
                    await asyncio.sleep(0.6 * (2**attempt))
                    continue
                raise

        if last_exc:
            raise last_exc
        return {}

    # ------------------------------ helpers de payload

    def _unwrap_payload(self, data: Any) -> Any:
        if not isinstance(data, dict):
            return None
        if "payload" in data:
            return data.get("payload")
        inner = data.get("data")
        if isinstance(inner, dict) and "payload" in inner:
            return inner.get("payload")
        return None

    # ------------------------------ mídia / paths locais

    def _media_root(self) -> Path:
        base = getattr(settings, "MEDIA_ROOT", None)
        return Path(base) if base else Path("media")

    def _resolve_local_media_path(self, incident_id: int, media_url: str) -> Optional[Path]:
        if not media_url:
            return None
        try:
            parsed = urlparse(media_url)
            path = parsed.path or media_url
            parts = path.strip("/").split("/")
            if "incidents" not in parts:
                return None
            idx = parts.index("incidents")
            if len(parts) < idx + 3:
                return None
            rel = Path(*parts[idx:])  # incidents/{id}/arquivo.ext
            return self._media_root() / rel
        except Exception:
            logger.exception("[chatwoot] erro ao resolver path local para media_url=%r", media_url)
            return None

    def _chatwoot_file_type(self, media_type: Optional[str]) -> str:
        mt = (media_type or "").upper()
        if mt == "IMAGE":
            return "image"
        if mt == "VIDEO":
            return "video"
        if mt == "AUDIO":
            return "audio"
        return "document"

    def _format_author_content(self, author_name: Optional[str], content: str) -> str:
        base = (content or "").strip()
        author = (author_name or "").strip()
        if not author:
            return base
        if not base:
            return author
        return f"{author}:\n{base}"

    def _looks_like_duplicate_source_id(self, status_code: int, body_text: str) -> bool:
        if status_code != 422:
            return False
        bt = (body_text or "").lower()
        # Mensagens variam por versão/instalação
        return (
            "has already been taken" in bt
            or "already taken" in bt
            or "source" in bt
            or "source_id" in bt
            or "source id" in bt
        )

    # ------------------------------ inbox / contact

    async def _resolve_inbox_id(self, identifier: str) -> Optional[int]:
        if not identifier:
            return None

        if identifier in self._inbox_cache:
            return self._inbox_cache[identifier]

        if identifier.isdigit():
            inbox_id = int(identifier)
            self._inbox_cache[identifier] = inbox_id
            return inbox_id

        data = await self._request("GET", f"/api/v1/accounts/{self.account_id}/inboxes")
        payload = data.get("payload") or []

        for inbox in payload:
            if inbox.get("identifier") == identifier or inbox.get("name") == identifier:
                inbox_id = int(inbox["id"])
                self._inbox_cache[identifier] = inbox_id
                return inbox_id

        logger.warning("[chatwoot] inbox com identifier/name '%s' não encontrada.", identifier)
        return None

    async def _find_contact_id_by_identifier(self, identifier: str) -> Optional[int]:
        if not identifier:
            return None

        attempts = [{"q": identifier}, {"identifier": identifier}]

        for params in attempts:
            try:
                data = await self._request(
                    "GET",
                    f"/api/v1/accounts/{self.account_id}/contacts/search",
                    params=params,
                )
            except ChatwootHTTPError:
                continue

            payload = data.get("payload") if isinstance(data, dict) else None

            if isinstance(payload, list):
                for c in payload:
                    if isinstance(c, dict) and c.get("identifier") == identifier and c.get("id") is not None:
                        return int(c["id"])
                for c in payload:
                    if isinstance(c, dict) and c.get("id") is not None:
                        return int(c["id"])

            if isinstance(payload, dict):
                cid = payload.get("id")
                if cid is not None:
                    return int(cid)
                contact = payload.get("contact")
                if isinstance(contact, dict) and contact.get("id") is not None:
                    return int(contact["id"])

            if isinstance(data, dict) and data.get("id") is not None:
                return int(data["id"])

        return None

    async def _get_or_create_contact(self, identifier: str) -> Optional[int]:
        if not identifier:
            return None

        if identifier in self._contact_cache:
            return self._contact_cache[identifier]

        existing = await self._find_contact_id_by_identifier(identifier)
        if existing:
            self._contact_cache[identifier] = existing
            return existing

        body = {"identifier": identifier, "name": "SecurityVision"}

        try:
            data = await self._request(
                "POST",
                f"/api/v1/accounts/{self.account_id}/contacts",
                json=body,
            )
        except ChatwootHTTPError as e:
            if e.status_code == 422 and "identifier has already been taken" in (e.body_text or "").lower():
                recovered = await self._find_contact_id_by_identifier(identifier)
                if recovered:
                    self._contact_cache[identifier] = recovered
                    return recovered
            raise

        payload = data.get("payload") if isinstance(data, dict) else None
        contact = payload["contact"] if isinstance(payload, dict) and isinstance(payload.get("contact"), dict) else payload
        cid = int(contact["id"]) if isinstance(contact, dict) and contact.get("id") else None

        if not cid:
            logger.warning("[chatwoot] resposta de criação de contact sem id: %r", data)
            return None

        self._contact_cache[identifier] = cid
        return cid

    # ------------------------------ conversas

    async def _find_conversation_for_incident(
        self,
        *,
        inbox_id: int,
        incident_id: int,
        incident_created_at: Optional[str],
    ) -> Optional[int]:
        filters: list[dict[str, Any]] = [
            {
                "attribute_key": "incident_id",
                "filter_operator": "equal_to",
                "values": [str(incident_id)],
                "query_operator": "AND",
            },
            {
                "attribute_key": "inbox_id",
                "filter_operator": "equal_to",
                "values": [str(inbox_id)],
                "query_operator": "AND",
            },
        ]

        if incident_created_at:
            filters.insert(
                1,
                {
                    "attribute_key": "incident_created_at",
                    "filter_operator": "equal_to",
                    "values": [incident_created_at],
                    "query_operator": "AND",
                },
            )

        try:
            data = await self._request(
                "POST",
                f"/api/v1/accounts/{self.account_id}/conversations/filter",
                json={"payload": filters},
            )
        except ChatwootHTTPError:
            return None

        payload = self._unwrap_payload(data)
        if isinstance(payload, list) and payload:
            first = payload[0]
            if isinstance(first, dict) and first.get("id") is not None:
                return int(first["id"])
        return None

    async def _ensure_conversation(self, incident: Incident) -> Optional[int]:
        if incident.chatwoot_conversation_id:
            return int(incident.chatwoot_conversation_id)

        incident_created_at: Optional[str] = None
        if getattr(incident, "created_at", None):
            try:
                incident_created_at = incident.created_at.isoformat()
            except Exception:
                incident_created_at = None

        group = getattr(incident, "assigned_group", None)
        inbox_identifier = (getattr(group, "chatwoot_inbox_identifier", None) or self.default_inbox_identifier)
        inbox_id = await self._resolve_inbox_id(inbox_identifier)
        if not inbox_id:
            logger.warning("[chatwoot] não consegui resolver inbox_id para incidente %s", incident.id)
            return None

        existing_conv_id = await self._find_conversation_for_incident(
            inbox_id=inbox_id,
            incident_id=incident.id,
            incident_created_at=incident_created_at,
        )
        if existing_conv_id:
            return existing_conv_id

        contact_identifier = self.default_contact_identifier or "securityvision-system"
        contact_id = await self._get_or_create_contact(contact_identifier)
        if not contact_id:
            logger.warning("[chatwoot] não consegui resolver contact_id para incidente %s", incident.id)
            return None

        body: dict[str, Any] = {
            "source_id": f"incident-{incident.id}",
            "inbox_id": inbox_id,
            "contact_id": contact_id,
            "status": "open",
            "custom_attributes": {
                "incident_id": incident.id,
                "incident_created_at": incident_created_at,
                "severity": incident.severity,
                "status": incident.status,
                "tenant": incident.tenant,
                "device_id": incident.device_id,
            },
        }

        team_id = getattr(group, "chatwoot_team_id", None)
        if team_id:
            body["team_id"] = team_id

        try:
            data = await self._request(
                "POST",
                f"/api/v1/accounts/{self.account_id}/conversations",
                json=body,
            )
        except ChatwootHTTPError as e:
            if e.status_code == 422:
                recovered = await self._find_conversation_for_incident(
                    inbox_id=inbox_id,
                    incident_id=incident.id,
                    incident_created_at=incident_created_at,
                )
                if recovered:
                    return recovered
            raise

        payload = data.get("payload") or data
        conv_id = payload.get("id")
        if not conv_id:
            logger.warning("[chatwoot] resposta de criação de conversation sem id: %r", data)
            return None
        return int(conv_id)

    # ------------------------------ envio: attachment

    async def _send_attachment_message(self, conversation_id: int, message: IncidentMessage) -> bool:
        if not message.media_url:
            return False

        local_path = self._resolve_local_media_path(
            incident_id=message.incident_id,
            media_url=message.media_url,
        )
        if not local_path or not local_path.exists():
            logger.warning(
                "[chatwoot] não encontrei arquivo local para media_url=%r (incident_id=%s). path=%r media_root=%r",
                message.media_url,
                message.incident_id,
                str(local_path) if local_path else None,
                str(self._media_root()),
            )
            return False

        file_type = self._chatwoot_file_type(message.media_type)
        mime_type, _ = mimetypes.guess_type(local_path.name)
        mime_type = mime_type or "application/octet-stream"

        content = self._format_author_content(message.author_name, message.content or "")
        url_path = f"/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages"

        try:
            with local_path.open("rb") as f:
                files = {
                    "attachments[]": (local_path.name, f, mime_type),
                    "content": (None, content),
                    "message_type": (None, "outgoing"),
                    "private": (None, "true"),
                    "file_type": (None, file_type),
                    "content_attributes[sv_source]": (None, "securityvision"),
                    "source_id": (None, f"sv-msg-{message.id}"),
                }
                resp = await self._get_http().post(
                    f"{self.base_url}{url_path}",
                    headers=self._headers(),
                    files=files,
                    timeout=60.0,  # attachments podem ser mais lentos
                )

            if resp.status_code >= 400:
                body_text = resp.text or ""
                if self._looks_like_duplicate_source_id(resp.status_code, body_text):
                    # idempotência: se o Chatwoot já tem essa msg, tratamos como ok
                    logger.info(
                        "[chatwoot] attachment já enviado (422 duplicate source_id). incidente=%s msg=%s conv=%s",
                        message.incident_id,
                        message.id,
                        conversation_id,
                    )
                    return True

                logger.warning(
                    "[chatwoot] upload de attachment falhou (%s): %s",
                    resp.status_code,
                    body_text[:2000],
                )
                return False

            return True
        except Exception:
            logger.exception(
                "[chatwoot] erro ao enviar attachment do incidente %s (msg %s) para conversa %s",
                message.incident_id,
                message.id,
                conversation_id,
            )
            return False

    # ------------------------------ API pública

    async def send_incident_notification(self, incident: Incident, incident_url: Optional[str] = None) -> Optional[int]:
        if not self.is_configured():
            logger.info("[chatwoot] integração desabilitada/não configurada. incidente=%s", incident.id)
            return incident.chatwoot_conversation_id

        try:
            conversation_id = await self._ensure_conversation(incident)
        except Exception:
            logger.exception("[chatwoot] erro ao garantir conversation para incidente %s", incident.id)
            return incident.chatwoot_conversation_id

        if not conversation_id:
            return incident.chatwoot_conversation_id

        # ✅ importante: evita duplicar resumo em cascata de mensagens no mesmo request
        self._set_incident_conversation_id(incident, int(conversation_id))

        if not incident_url and self.incident_base_url:
            incident_url = f"{self.incident_base_url}/{incident.id}"

        summary_lines = [
            f"[Incidente #{incident.id}] {incident.title}",
            f"Status: {incident.status} | Severidade: {incident.severity}",
            f"Tenant: {incident.tenant or '-'} | Dispositivo: {incident.device_id}",
        ]
        if incident.assigned_group:
            summary_lines.append(
                f"Grupo: {incident.assigned_group.name} (team_id={incident.assigned_group.chatwoot_team_id or '-'})"
            )
        if incident_url:
            summary_lines.append(f"Acesse: {incident_url}")

        content = "\n".join(summary_lines)

        try:
            await self._request(
                "POST",
                f"/api/v1/accounts/{self.account_id}/conversations/{int(conversation_id)}/messages",
                json={
                    "content": content,
                    "message_type": "outgoing",
                    "private": True,
                    "source_id": f"sv-incident-{incident.id}",
                    "content_attributes": {"sv_source": "securityvision"},
                },
            )
        except ChatwootHTTPError as e:
            if e.status_code != 422:
                logger.exception("[chatwoot] erro ao enviar mensagem inicial do incidente %s", incident.id)
        except Exception:
            logger.exception("[chatwoot] erro ao enviar mensagem inicial do incidente %s", incident.id)

        return int(conversation_id)

    async def send_incident_timeline_message(
        self,
        incident: Incident,
        message: IncidentMessage,
        incident_url: Optional[str] = None,
    ) -> None:
        if not self.is_configured():
            logger.info("[chatwoot] integração desabilitada. incidente=%s msg=%s", incident.id, message.id)
            return

        conversation_id = incident.chatwoot_conversation_id
        if not conversation_id:
            conversation_id = await self.send_incident_notification(incident, incident_url=incident_url)
            if not conversation_id:
                return

        # ✅ garante “cache” local no objeto (evita loops de resumo)
        self._set_incident_conversation_id(incident, int(conversation_id))

        # tenta attachment primeiro
        if message.message_type == "MEDIA" and message.media_url:
            ok = await self._send_attachment_message(int(conversation_id), message)
            if ok:
                return

        content = self._format_author_content(message.author_name, message.content or "")

        if message.message_type == "MEDIA" and message.media_url:
            media_line = f"[arquivo anexado]: {message.media_url}"
            content = f"{content}\n\n{media_line}" if content else media_line

        if not content:
            return

        try:
            await self._request(
                "POST",
                f"/api/v1/accounts/{self.account_id}/conversations/{int(conversation_id)}/messages",
                json={
                    "content": content,
                    "message_type": "outgoing",
                    "private": True,
                    "source_id": f"sv-msg-{message.id}",
                    "content_attributes": {"sv_source": "securityvision"},
                },
            )
        except ChatwootHTTPError as e:
            if e.status_code != 422:
                logger.exception("[chatwoot] erro ao enviar msg=%s incidente=%s", message.id, incident.id)
        except Exception:
            logger.exception("[chatwoot] erro ao enviar msg=%s incidente=%s", message.id, incident.id)
