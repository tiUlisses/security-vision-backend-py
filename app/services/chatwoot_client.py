# app/services/chatwoot_client.py
from __future__ import annotations

from typing import Optional, Any
import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.models.incident import Incident
from app.models.incident_message import IncidentMessage

logger = logging.getLogger(__name__)


class ChatwootClient:
    """
    Cliente de integração com Chatwoot.

    - Usa feature flag (CHATWOOT_ENABLED).
    - Faz chamadas HTTP reais usando httpx.
    - Cria/usa contact "sistema" (default_contact_identifier).
    - Cria/usa conversation por incidente (source_id = incident-{id}).
    - Atribui para inbox/time correto quando houver SupportGroup.
    - Envia notas privadas e, quando for mídia, envia também como attachment.

    Qualquer erro aqui deve ser "best-effort":
    loga, mas NÃO quebra fluxo de incident.
    """

    def __init__(self) -> None:
        self.enabled = settings.CHATWOOT_ENABLED

        # CHATWOOT_BASE_URL pode ser AnyHttpUrl (Url do pydantic), então converte pra str
        raw_base = settings.CHATWOOT_BASE_URL
        if raw_base:
            self.base_url = str(raw_base).rstrip("/")
        else:
            self.base_url = ""

        self.token = settings.CHATWOOT_API_ACCESS_TOKEN
        self.account_id = settings.CHATWOOT_DEFAULT_ACCOUNT_ID

        self.default_inbox_identifier = settings.CHATWOOT_DEFAULT_INBOX_IDENTIFIER
        self.default_contact_identifier = settings.CHATWOOT_DEFAULT_CONTACT_IDENTIFIER

        # URL base para acessar o incidente no frontend
        raw_incident_base = settings.CHATWOOT_INCIDENT_BASE_URL
        if raw_incident_base:
            self.incident_base_url = str(raw_incident_base).rstrip("/")
        else:
            self.incident_base_url = None

        # caches simples em memória
        self._inbox_cache: dict[str, int] = {}
        self._contact_cache: dict[str, int] = {}

    # ------------------------------------------------------------------ helpers básicos

    def is_configured(self) -> bool:
        return bool(
            self.enabled
            and self.base_url
            and self.token
            and self.account_id
            and self.default_inbox_identifier
        )

    def _headers_json(self) -> dict[str, str]:
        """
        Headers para chamadas JSON (usa Content-Type: application/json).
        NÃO usar para multipart/form-data (attachments).
        """
        return {
            "api_access_token": self.token or "",
            "Content-Type": "application/json",
        }

    def _headers_multipart(self) -> dict[str, str]:
        """
        Headers para chamadas multipart/form-data.

        Não setamos Content-Type, o httpx define com boundary automaticamente.
        """
        return {
            "api_access_token": self.token or "",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """
        Helper genérico de request JSON.

        Lança RuntimeError em erro HTTP; o chamador deve tratar (try/except)
        para não quebrar o fluxo principal.
        """
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(
                method,
                url,
                headers=self._headers_json(),
                **kwargs,
            )

        if resp.status_code >= 400:
            logger.warning(
                "[chatwoot] HTTP %s %s falhou: %s %s",
                method,
                url,
                resp.status_code,
                resp.text,
            )
            raise RuntimeError(
                f"Chatwoot HTTP error {resp.status_code} for {method} {path}"
            )

        try:
            return resp.json()
        except ValueError:
            return {}

    # ------------------------------------------------------------------ helpers de mídia / paths locais

    def _media_root(self) -> Path:
        """
        Mesmo conceito do incident_files._get_media_root():
        - Usa settings.MEDIA_ROOT se existir, senão 'media'.
        """
        base = getattr(settings, "MEDIA_ROOT", None)
        if base:
            return Path(base)
        return Path("media")

    def _resolve_local_media_path(self, incident_id: int, media_url: str) -> Optional[Path]:
        """
        Converte a media_url de um IncidentMessage (que normalmente é
        /media/incidents/{incident_id}/arquivo.ext
        OU {MEDIA_BASE_URL}/incidents/{incident_id}/arquivo.ext)
        para o path real no disco: MEDIA_ROOT/incidents/{incident_id}/arquivo.ext
        """
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
                # incidents / {id} / file
                return None

            # Opcionalmente poderíamos conferir o id
            # parts[idx+1] deveria ser str(incident_id), mas não vamos travar se não for
            rel = Path(*parts[idx:])  # incidents/{id}/arquivo.ext
            local_path = self._media_root() / rel
            return local_path
        except Exception:
            logger.exception(
                "[chatwoot] erro ao resolver path local para media_url=%r",
                media_url,
            )
            return None

    def _chatwoot_file_type(self, media_type: Optional[str]) -> str:
        """
        Converte IncidentMessage.media_type (IMAGE/VIDEO/AUDIO/FILE)
        para file_type aceito pelo Chatwoot (image/video/audio/document).
        """
        mt = (media_type or "").upper()
        if mt == "IMAGE":
            return "image"
        if mt == "VIDEO":
            return "video"
        if mt == "AUDIO":
            return "audio"
        # default
        return "document"

    # ------------------------------------------------------------------ inbox / contact

    async def _resolve_inbox_id(self, identifier: str) -> Optional[int]:
        """
        identifier pode ser:
        - id numérico em string: "1"
        - ou o identifier/name da inbox no chatwoot.
        """
        if not identifier:
            return None

        if identifier in self._inbox_cache:
            return self._inbox_cache[identifier]

        # se for só número, já usa direto
        if identifier.isdigit():
            inbox_id = int(identifier)
            self._inbox_cache[identifier] = inbox_id
            return inbox_id

        data = await self._request(
            "GET",
            f"/api/v1/accounts/{self.account_id}/inboxes",
        )
        payload = data.get("payload") or []

        for inbox in payload:
            if (
                inbox.get("identifier") == identifier
                or inbox.get("name") == identifier
            ):
                inbox_id = int(inbox["id"])
                self._inbox_cache[identifier] = inbox_id
                return inbox_id

        logger.warning(
            "[chatwoot] inbox com identifier/name '%s' não encontrada.",
            identifier,
        )
        return None

    async def _get_or_create_contact(self, identifier: str) -> Optional[int]:
        """
        Usa o campo 'identifier' do contact no chatwoot.
        """
        if not identifier:
            return None

        if identifier in self._contact_cache:
            return self._contact_cache[identifier]

        # tenta buscar
        data = await self._request(
            "GET",
            f"/api/v1/accounts/{self.account_id}/contacts/search",
            params={"identifier": identifier},
        )
        payload = data.get("payload") or {}

        contact_id = payload.get("id")
        if contact_id:
            cid = int(contact_id)
            self._contact_cache[identifier] = cid
            return cid

        # não existe: cria
        body = {
            "identifier": identifier,
            "name": "SecurityVision",
        }
        data = await self._request(
            "POST",
            f"/api/v1/accounts/{self.account_id}/contacts",
            json=body,
        )
        payload = data.get("payload") or data
        contact_id = payload.get("id")
        if not contact_id:
            logger.warning(
                "[chatwoot] não foi possível obter id do contact para identifier=%s",
                identifier,
            )
            return None

        cid = int(contact_id)
        self._contact_cache[identifier] = cid
        return cid

    # ------------------------------------------------------------------ conversas

    async def _ensure_conversation(self, incident: Incident) -> Optional[int]:
        """
        Garante que exista uma conversation para este incidente.

        - Se já tiver chatwoot_conversation_id no incidente, usa direto.
        - Senão, cria conversation com:
          - inbox do grupo (ou default)
          - team_id do grupo (se tiver)
          - contact default (identifier global)
          - source_id = incident-{id}
        """
        if incident.chatwoot_conversation_id:
            return incident.chatwoot_conversation_id

        group = getattr(incident, "assigned_group", None)

        inbox_identifier = (
            getattr(group, "chatwoot_inbox_identifier", None)
            or self.default_inbox_identifier
        )
        inbox_id = await self._resolve_inbox_id(inbox_identifier)
        if not inbox_id:
            logger.warning(
                "[chatwoot] não consegui resolver inbox_id para incidente %s",
                incident.id,
            )
            return None

        contact_identifier = (
            self.default_contact_identifier or "securityvision-system"
        )
        contact_id = await self._get_or_create_contact(contact_identifier)
        if not contact_id:
            logger.warning(
                "[chatwoot] não consegui resolver contact_id para incidente %s",
                incident.id,
            )
            return None

        body: dict[str, Any] = {
            "source_id": f"incident-{incident.id}",
            "inbox_id": inbox_id,
            "contact_id": contact_id,
            "status": "open",
            "custom_attributes": {
                "incident_id": incident.id,
                "severity": incident.severity,
                "status": incident.status,
                "tenant": incident.tenant,
            },
        }

        team_id = getattr(group, "chatwoot_team_id", None)
        if team_id:
            # se não tiver grupo, NÃO manda team_id → conversa fica "para todos"
            body["team_id"] = team_id

        data = await self._request(
            "POST",
            f"/api/v1/accounts/{self.account_id}/conversations",
            json=body,
        )
        payload = data.get("payload") or data
        conv_id = payload.get("id")
        if not conv_id:
            logger.warning(
                "[chatwoot] resposta de criação de conversation sem id: %r",
                data,
            )
            return None

        return int(conv_id)

    # ------------------------------------------------------------------ envio de mensagem com attachment

    async def _send_attachment_message(
        self,
        conversation_id: int,
        message: IncidentMessage,
    ) -> bool:
        """
        Envia uma mensagem com attachment para a conversation no Chatwoot.

        Usa multipart/form-data:

        - attachments[] (arquivo)
        - content
        - message_type = outgoing
        - private = true
        - file_type = image|video|audio|document
        """
        if not message.media_url:
            return False

        local_path = self._resolve_local_media_path(
            incident_id=message.incident_id,
            media_url=message.media_url,
        )
        if not local_path or not local_path.exists():
            logger.warning(
                "[chatwoot] não encontrei arquivo local para media_url=%r (incident_id=%s)",
                message.media_url,
                message.incident_id,
            )
            return False

        file_type = self._chatwoot_file_type(message.media_type)
        mime_type, _ = mimetypes.guess_type(local_path.name)
        if not mime_type:
            mime_type = "application/octet-stream"

        # conteúdo de texto (incluindo nome do operador, se houver)
        base_content = (message.content or "").strip()
        author = (message.author_name or "").strip()
        if author:
            if base_content:
                content = f"{author}:\n{base_content}"
            else:
                content = author
        else:
            content = base_content

        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                with local_path.open("rb") as f:
                    files = {
                        "attachments[]": (local_path.name, f, mime_type),
                        "content": (None, content),
                        "message_type": (None, "outgoing"),
                        "private": (None, "true"),
                        "file_type": (None, file_type),
                        # 👇 Rails-style para nested params: content_attributes[sv_source] -> { content_attributes: { sv_source: "securityvision" } }
                        "content_attributes[sv_source]": (None, "securityvision"),
                        "source_id": (None, f"sv-msg-{message.id}"),
                    }
                    resp = await client.post(
                        url,
                        headers=self._headers_multipart(),
                        files=files,
                    )

            if resp.status_code >= 400:
                logger.warning(
                    "[chatwoot] upload de attachment falhou (%s): %s",
                    resp.status_code,
                    resp.text,
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

    # ------------------------------------------------------------------ API pública: incidente criado/atualizado

    async def send_incident_notification(
        self,
        incident: Incident,
        incident_url: Optional[str] = None,
    ) -> Optional[int]:
        """
        Envia (ou atualiza) uma mensagem no Chatwoot referente a este incidente.

        - Garante que exista uma conversation (ver _ensure_conversation).
        - Envia uma nota privada com resumo + link do incidente.
        - Retorna o conversation_id se conseguir, senão None.
        """

        if not self.is_configured():
            logger.info(
                "[chatwoot] integração desabilitada ou não configurada. "
                "Não enviando notificação para incidente %s.",
                incident.id,
            )
            return incident.chatwoot_conversation_id

        try:
            conversation_id = await self._ensure_conversation(incident)
        except Exception:
            logger.exception(
                "[chatwoot] erro ao garantir conversation para incidente %s",
                incident.id,
            )
            return incident.chatwoot_conversation_id

        if not conversation_id:
            return incident.chatwoot_conversation_id

        # monta URL amigável se não vier explícita
        if not incident_url and self.incident_base_url:
            incident_url = f"{self.incident_base_url}/{incident.id}"

        summary_lines = [
            f"[Incidente #{incident.id}] {incident.title}",
            f"Status: {incident.status} | Severidade: {incident.severity}",
            f"Tenant: {incident.tenant or '-'} | Dispositivo: {incident.device_id}",
        ]
        if incident.assigned_group:
            summary_lines.append(
                f"Grupo: {incident.assigned_group.name} "
                f"(team_id={incident.assigned_group.chatwoot_team_id or '-'})"
            )
        if incident_url:
            summary_lines.append(f"Acesse: {incident_url}")

        content = "\n".join(summary_lines)

        try:
            await self._request(
                "POST",
                f"/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages",
                json={
                    "content": content,
                    "message_type": "outgoing",
                    "private": True,  # nota interna
                    "source_id": f"sv-incident-{incident.id}",  # 👈 marca como vindo do SV
                    "content_attributes": {
                        "sv_source": "securityvision",
                    },
                },
            )
        except Exception:
            logger.exception(
                "[chatwoot] erro ao enviar mensagem inicial do incidente %s",
                incident.id,
            )

        return conversation_id

    async def send_incident_timeline_message(
        self,
        incident: Incident,
        message: IncidentMessage,
        incident_url: Optional[str] = None,
    ) -> None:
        """
        Envia uma mensagem da timeline do incidente para a conversa
        correspondente no Chatwoot como nota privada.

        - Se o incidente ainda não tem conversation, chama send_incident_notification.
        - Se for mensagem de mídia (MEDIA), tenta enviar como attachment.
        """

        if not self.is_configured():
            logger.info(
                "[chatwoot] integração desabilitada. "
                "Não enviando mensagem %s do incidente %s.",
                message.id,
                incident.id,
            )
            return

        conversation_id = incident.chatwoot_conversation_id
        if not conversation_id:
            # tenta criar conversation e mandar resumo primeiro
            conversation_id = await self.send_incident_notification(
                incident,
                incident_url=incident_url,
            )
            if not conversation_id:
                return

        # Se for mídia, tentamos attachment primeiro
        if message.message_type == "MEDIA" and message.media_url:
            ok = await self._send_attachment_message(conversation_id, message)
            if ok:
                # já mandamos com arquivo + texto, não precisa mandar nota extra
                return
            # se falhar, caímos no fallback de texto com link

        # Fallback / mensagens não-MEDIA: nota de texto simples
        base_content = (message.content or "").strip()
        author = (message.author_name or "").strip()
        if author:
            if base_content:
                content = f"{author}:\n{base_content}"
            else:
                content = author
        else:
            content = base_content

        # Se for mídia e não conseguimos attachment, adiciona link
        if message.message_type == "MEDIA" and message.media_url:
            media_line = f"[arquivo anexado]: {message.media_url}"
            if content:
                content = content + "\n\n" + media_line
            else:
                content = media_line

        # Se for mídia e não conseguimos attachment, adiciona link
        if message.message_type == "MEDIA" and message.media_url:
            media_line = f"[arquivo anexado]: {message.media_url}"
            if content:
                content = content + "\n\n" + media_line
            else:
                content = media_line

        if not content:
            return

        try:
            await self._request(
                "POST",
                f"/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages",
                json={
                    "content": content,  # 👈 agora usamos o content completo
                    "message_type": "outgoing",
                    "private": True,
                    "source_id": f"sv-msg-{message.id}",  # 👈 marca que veio do SV
                    "content_attributes": {
                        "sv_source": "securityvision",
                    },
                },
            )
        except Exception:
            logger.exception(
                "[chatwoot] erro ao enviar mensagem %s do incidente %s",
                message.id,
                incident.id,
            )
