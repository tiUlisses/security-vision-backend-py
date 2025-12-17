# app/api/routes/chatwoot_webhooks.py
from __future__ import annotations

from typing import Any, Dict, Optional, List, Tuple
import logging
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_db_session
from app.core.config import settings
from app.crud import incident as crud_incident
from app.crud import incident_message as crud_incident_message
from app.schemas import IncidentMessageCreate
from app.services.incident_files import save_incident_image_from_url

# ✅ para DE→PARA Chatwoot -> SV
from app.models.user import User
from app.models.incident import Incident

logger = logging.getLogger(__name__)

router = APIRouter()

# Eventos que realmente queremos processar
MESSAGE_EVENTS = {"message_created", "message_updated"}


def _check_webhook_auth(x_chatwoot_signature: Optional[str]) -> None:
    """
    Modo DEV: só valida se CHATWOOT_WEBHOOK_TOKEN estiver configurado.
    Se não estiver, não bloqueia nada.
    """
    expected = getattr(settings, "CHATWOOT_WEBHOOK_TOKEN", None)

    if not expected:
        return

    if x_chatwoot_signature != expected:
        logger.warning(
            "[chatwoot-webhook] assinatura inválida: recebida=%r esperada=%r",
            x_chatwoot_signature,
            expected,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Chatwoot signature",
        )


def _truncate_text(text: str, max_chars: int) -> str:
    if not text:
        return text
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"...(truncado, len={len(text)})"


def _safe_json_dumps(obj: Any, *, max_chars: int) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    except Exception:
        s = repr(obj)
    return _truncate_text(s, max_chars)


def _log_incoming_webhook(request: Request, raw_body_text: str, payload: Dict[str, Any]) -> None:
    """
    Log detalhado do webhook (para você capturar o payload real).
    Controlável por settings.
    """
    enabled = getattr(settings, "CHATWOOT_WEBHOOK_LOG_PAYLOAD", True)
    if not enabled:
        return

    max_chars = int(getattr(settings, "CHATWOOT_WEBHOOK_LOG_MAX_CHARS", 12_000))

    headers = {}
    try:
        for k, v in request.headers.items():
            kl = k.lower()
            if kl in ("authorization", "cookie"):
                continue
            headers[k] = v
    except Exception:
        headers = {"_error": "failed_to_read_headers"}

    logger.warning("[chatwoot-webhook] REQUEST %s %s", request.method, str(request.url))
    logger.warning("[chatwoot-webhook] HEADERS: %s", _safe_json_dumps(headers, max_chars=4000))

    if raw_body_text:
        logger.warning(
            "[chatwoot-webhook] RAW BODY (len=%s): %s",
            len(raw_body_text),
            _truncate_text(raw_body_text, max_chars),
        )

    logger.warning(
        "[chatwoot-webhook] PARSED JSON: %s",
        _safe_json_dumps(payload, max_chars=max_chars),
    )


def _extract_event(payload: Dict[str, Any]) -> Optional[str]:
    event = payload.get("event") or payload.get("event_name")
    if isinstance(event, str) and event.strip():
        return event.strip()
    return None


def _extract_conversation_id(payload: Dict[str, Any]) -> Optional[int]:
    data = payload.get("data") or payload
    conversation = data.get("conversation") or {}
    conversation_id = (
        conversation.get("id")
        or data.get("conversation_id")
        or payload.get("conversation_id")
    )
    if not conversation_id:
        return None
    try:
        return int(conversation_id)
    except (TypeError, ValueError):
        return None


def _extract_message_obj(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Chatwoot pode mandar:
    - message no payload["message"]
    - message em payload["data"]["message"]
    - ou campos da msg direto no root (como no seu log)
    """
    data = payload.get("data") or payload
    msg = data.get("message") or payload.get("message") or data
    return msg if isinstance(msg, dict) else {}


def _extract_attachments(message: Dict[str, Any], data: Dict[str, Any]) -> List[Dict[str, Any]]:
    attachments = message.get("attachments")
    if not attachments:
        attachments = data.get("attachments") or []
    if not isinstance(attachments, list):
        return []
    return [a for a in attachments if isinstance(a, dict)]


def _extract_incident_id(payload: Dict[str, Any]) -> Optional[int]:
    """
    Fallback robusto:
    - conversation.custom_attributes.incident_id
    - conversation.contact_inbox.source_id = "incident-81"
    """
    data = payload.get("data") or payload
    conversation = data.get("conversation") or payload.get("conversation") or {}
    if not isinstance(conversation, dict):
        return None

    custom = conversation.get("custom_attributes") or {}
    if isinstance(custom, dict):
        inc_id = custom.get("incident_id")
        if isinstance(inc_id, int):
            return inc_id
        if isinstance(inc_id, str) and inc_id.isdigit():
            return int(inc_id)

    contact_inbox = conversation.get("contact_inbox") or {}
    if isinstance(contact_inbox, dict):
        source_id = contact_inbox.get("source_id")
        if isinstance(source_id, str) and source_id.startswith("incident-"):
            suffix = source_id.split("incident-", 1)[-1]
            if suffix.isdigit():
                return int(suffix)

    return None


def _is_message_from_securityvision(message: Dict[str, Any]) -> bool:
    """
    Evita loop:
    - content_attributes.sv_source == securityvision
    - source_id começa com sv-
    """
    content_attributes = message.get("content_attributes") or {}
    if isinstance(content_attributes, dict) and content_attributes.get("sv_source") == "securityvision":
        return True

    source_id = message.get("source_id")
    if isinstance(source_id, str) and source_id.startswith("sv-"):
        return True

    return False


def _normalize_msg_type(raw: Any) -> str:
    """
    Chatwoot pode mandar message_type como:
    - "incoming"/"outgoing"
    - ou int (0/1) dentro de alguns objetos
    """
    if isinstance(raw, str):
        return raw.lower().strip()
    if isinstance(raw, int):
        return "outgoing" if raw == 1 else "incoming"
    return "incoming"


def _extract_private(message: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    for key in ("private", "is_private"):
        v = message.get(key)
        if isinstance(v, bool):
            return v
        v2 = payload.get(key)
        if isinstance(v2, bool):
            return v2
    return False


async def _resolve_author_name(db: AsyncSession, sender: Dict[str, Any]) -> str:
    """
    ✅ DE→PARA:
    Chatwoot sender.id (user) -> User.chatwoot_agent_id (SV)
    """
    sender_type = str(sender.get("type") or "").lower()
    sender_id = sender.get("id")

    if sender_type == "user" and isinstance(sender_id, int):
        res = await db.execute(select(User).where(User.chatwoot_agent_id == sender_id).limit(1))
        user = res.scalar_one_or_none()
        if user:
            # prioriza full_name, depois email
            full_name = getattr(user, "full_name", None)
            email = getattr(user, "email", None)
            return (full_name or email or sender.get("name") or "Operador").strip()

    # fallback
    return str(sender.get("name") or sender.get("email") or "Chatwoot").strip()


@router.post("/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def chatwoot_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    x_chatwoot_signature: str | None = Header(default=None),
):
    """
    Webhook do Chatwoot em:
    /api/v1/integrations/chatwoot/webhook
    (via api_router.include_router(prefix="/integrations/chatwoot"))
    """
    logger.warning("[chatwoot-webhook] HIT")

    _check_webhook_auth(x_chatwoot_signature)

    body_bytes = await request.body()
    raw_body_text = body_bytes.decode("utf-8", errors="replace") if body_bytes else ""

    payload: Dict[str, Any] = {}
    if raw_body_text.strip():
        try:
            payload = json.loads(raw_body_text)
            if not isinstance(payload, dict):
                payload = {"_raw": payload}
        except Exception:
            payload = {"_raw_text": raw_body_text}

    event = _extract_event(payload)
    logger.warning("[chatwoot-webhook] event=%r", event)

    # ✅ ignora eventos que não são mensagens (typing, status etc)
    if not event or event not in MESSAGE_EVENTS:
        logger.info("[chatwoot-webhook] ignorando event=%r", event)
        return

    # ✅ log detalhado apenas para eventos de mensagem (reduz ruído)
    _log_incoming_webhook(request, raw_body_text, payload)

    conversation_id = _extract_conversation_id(payload)
    logger.warning("[chatwoot-webhook] conversation_id extraído = %r", conversation_id)

    data = payload.get("data") or payload
    message = _extract_message_obj(payload)
    attachments = _extract_attachments(message, data)

    # evita loop: mensagens originadas do SV
    if _is_message_from_securityvision(message):
        logger.info("[chatwoot-webhook] mensagem originada do SecurityVision, ignorando para evitar loop.")
        return

    # sender pode vir em lugares diferentes; para message_created geralmente vem em message.sender ou payload.sender
    sender = (
        message.get("sender")
        or data.get("sender")
        or payload.get("sender")
        or payload.get("user")  # alguns eventos mandam user
        or {}
    )
    if not isinstance(sender, dict):
        sender = {}

    logger.warning("[chatwoot-webhook] sender(raw)=%s", _safe_json_dumps(sender, max_chars=4000))

    # 🔎 1) tenta achar por conversation_id (fluxo atual)
    incident = None
    if conversation_id:
        incident = await crud_incident.get_by_chatwoot_conversation(db, conversation_id=conversation_id)

    # 🔎 2) fallback: acha incidente pelo incident_id dentro do payload
    if not incident:
        incident_id = _extract_incident_id(payload)
        if incident_id:
            res = await db.execute(select(Incident).where(Incident.id == incident_id).limit(1))
            incident = res.scalar_one_or_none()

            # se achou, atualiza o conversation_id no incidente (fica robusto p/ próximos webhooks)
            if incident and conversation_id:
                try:
                    current = getattr(incident, "chatwoot_conversation_id", None)
                    if current != conversation_id:
                        incident.chatwoot_conversation_id = conversation_id
                        await db.commit()
                except Exception:
                    await db.rollback()

    if not incident:
        logger.warning(
            "[chatwoot-webhook] não encontrei incidente por conversation_id=%s e nem por incident_id no payload",
            conversation_id,
        )
        return

    content = (message.get("content") or "").strip()

    raw_msg_type = message.get("message_type") or message.get("type") or "incoming"
    msg_type = _normalize_msg_type(raw_msg_type)

    is_private = _extract_private(message, payload)

    author_name = await _resolve_author_name(db, sender)

    logger.warning(
        "[chatwoot-webhook] incident_id=%s msg_type=%s private=%s author=%r content_len=%s attachments=%d",
        incident.id,
        msg_type,
        is_private,
        author_name,
        len(content),
        len(attachments),
    )

    if attachments:
        logger.warning("[chatwoot-webhook] attachments(raw)=%s", _safe_json_dumps(attachments, max_chars=8000))

    # Se não tem texto e não tem anexo, não salva nada
    if not content and not attachments:
        return

    # ----------------------
    # 1) Texto
    # ----------------------
    if content:
        # ✅ melhor alinhado com o frontend: SYSTEM vs OPERATOR
        message_type = "SYSTEM" if is_private else "OPERATOR"

        msg_in = IncidentMessageCreate(
            message_type=message_type,
            content=content,
            author_name=author_name,
        )
        data_to_save = msg_in.model_dump()
        data_to_save["incident_id"] = incident.id

        await crud_incident_message.create(db, obj_in=data_to_save)
        logger.warning("[chatwoot-webhook] TEXTO salvo em incident_messages para incidente %s", incident.id)

    # ----------------------
    # 2) Anexos
    # ----------------------
    for att in attachments:
        try:
            data_url = att.get("data_url") or att.get("file_url") or att.get("url")
            if not data_url:
                continue

            fallback_title = att.get("fallback_title")
            file_name = fallback_title or att.get("file_name") or att.get("filename") or att.get("name")
            if not file_name:
                ext = att.get("extension") or ""
                if ext and not ext.startswith("."):
                    ext = f".{ext}"
                file_name = f"chatwoot-attachment-{att.get('id', 'file')}{ext}"

            media_url, media_type, original_name = await save_incident_image_from_url(
                incident_id=incident.id,
                url=data_url,
                filename_hint=file_name,
            )

            attachment_label = f"Arquivo recebido via Chatwoot: {original_name}"
            if fallback_title and fallback_title != original_name:
                attachment_label += f" ({fallback_title})"

            media_msg_data = {
                "incident_id": incident.id,
                "message_type": "MEDIA",
                "content": attachment_label if not content else content,
                "media_type": media_type,
                "media_url": media_url,
                "media_thumb_url": None,
                "media_name": original_name,
                "author_name": author_name,
            }

            await crud_incident_message.create(db, obj_in=media_msg_data)

            logger.warning(
                "[chatwoot-webhook] ANEXO salvo em incident_messages incidente=%s type=%s url=%s",
                incident.id,
                media_type,
                media_url,
            )

        except Exception as exc:
            logger.exception("[chatwoot-webhook] erro ao processar attachment p/ incidente %s: %s", incident.id, exc)

    return
