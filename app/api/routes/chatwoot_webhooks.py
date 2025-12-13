# app/api/routes/chatwoot_webhooks.py
from __future__ import annotations

from typing import Any, Dict, Optional, List
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.config import settings
from app.crud import incident as crud_incident
from app.crud import incident_message as crud_incident_message
from app.schemas import IncidentMessageCreate
from app.services.incident_files import save_incident_image_from_url

logger = logging.getLogger(__name__)

router = APIRouter()


def _check_webhook_auth(x_chatwoot_signature: Optional[str]) -> None:
    """
    Modo DEV: só valida se CHATWOOT_WEBHOOK_TOKEN estiver configurado.
    Se não estiver, não bloqueia nada.
    """
    expected = getattr(settings, "CHATWOOT_WEBHOOK_TOKEN", None)

    # Se não tiver nada configurado, não valida (dev)
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
    data = payload.get("data") or payload
    return data.get("message") or data


def _extract_attachments(message: Dict[str, Any], data: Dict[str, Any]) -> List[Dict[str, Any]]:
    attachments = message.get("attachments")
    if not attachments:
        attachments = data.get("attachments") or []
    if not isinstance(attachments, list):
        return []
    return attachments


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

    # 💥 LOG FORÇADO pra sabermos que ESTE handler foi chamado
    logger.warning("[chatwoot-webhook] HIT")

    try:
        _check_webhook_auth(x_chatwoot_signature)
    except HTTPException:
        logger.warning("[chatwoot-webhook] assinatura inválida")
        raise

    payload: Dict[str, Any] = await request.json()
    logger.warning("[chatwoot-webhook] payload bruto: %r", payload)

    event = payload.get("event") or payload.get("event_name")
    logger.warning("[chatwoot-webhook] event=%r", event)

    # 👉 Temporariamente: NÃO filtrar por tipo de evento, pra garantir que estamos pegando
    # qualquer mensagem que chegue. Depois afinamos se quiser.
    # if not event or event not in (...):
    #     return

    conversation_id = _extract_conversation_id(payload)
    logger.warning("[chatwoot-webhook] conversation_id extraído = %r", conversation_id)

    if not conversation_id:
        logger.warning("[chatwoot-webhook] sem conversation_id válido, ignorando.")
        return

    incident = await crud_incident.get_by_chatwoot_conversation(
        db,
        conversation_id=conversation_id,
    )
    if not incident:
        logger.warning(
            "[chatwoot-webhook] não encontrei incidente com chatwoot_conversation_id=%s",
            conversation_id,
        )
        return

    data = payload.get("data") or payload
    message = _extract_message_obj(payload)
    attachments = _extract_attachments(message, data)

    content_attributes = message.get("content_attributes") or {}
    if isinstance(content_attributes, dict) and content_attributes.get("sv_source") == "securityvision":
        logger.info(
            "[chatwoot-webhook] mensagem originada do SecurityVision (sv_source=securityvision), ignorando."
        )
        return
    # 👇 NOVO 2: ignorar mensagens marcadas por source_id do SecurityVision
    source_id = message.get("source_id")
    if isinstance(source_id, str) and source_id.startswith("sv-"):
        logger.info(
            "[chatwoot-webhook] mensagem originada do SecurityVision (source_id=%s), ignorando para evitar loop.",
            source_id,
        )
        return

    content = message.get("content") or ""
    msg_type = message.get("message_type") or message.get("type") or "incoming"
    is_private = bool(message.get("private"))
    sender = message.get("sender") or data.get("sender") or {}
    author_name = sender.get("name") or sender.get("email") or "Chatwoot"

    logger.warning(
        "[chatwoot-webhook] incident_id=%s msg_type=%s private=%s author=%r content=%r attachments=%d",
        incident.id,
        msg_type,
        is_private,
        author_name,
        content,
        len(attachments),
    )

    # 1) Texto
    if content:
        message_type = "COMMENT"
        if is_private or msg_type in ("note", "private"):
            message_type = "SYSTEM"

        msg_in = IncidentMessageCreate(
            message_type=message_type,
            content=content,
            author_name=author_name,
        )
        data_to_save = msg_in.model_dump()
        data_to_save["incident_id"] = incident.id

        await crud_incident_message.create(db, obj_in=data_to_save)
        logger.warning(
            "[chatwoot-webhook] TEXTO salvo em incident_messages para incidente %s",
            incident.id,
        )

    # 2) Anexos
    for att in attachments:
        try:
            data_url = att.get("data_url") or att.get("file_url")
            if not data_url:
                continue

            fallback_title = att.get("fallback_title")
            file_name = (
                fallback_title
                or att.get("file_name")
                or att.get("filename")
            )
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
                "content": attachment_label,
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
            logger.exception(
                "[chatwoot-webhook] erro ao processar attachment para incidente %s: %s",
                incident.id,
                exc,
            )

    # 204 no content
    return
