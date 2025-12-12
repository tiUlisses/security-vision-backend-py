# app/api/routes/integrations_chatwoot.py
from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/integrations/chatwoot",
    tags=["integrations-chatwoot"],
)


@router.post("/webhook")
async def chatwoot_webhook(request: Request):
    """
    Endpoint que o Chatwoot vai chamar para avisar sobre:
    - novas mensagens
    - mudança de status de conversas, etc.

    Por enquanto é só um stub que faz log do payload.
    """
    payload = await request.json()
    logger.debug("[chatwoot] webhook payload recebido: %s", payload)

    if not settings.CHATWOOT_ENABLED:
        logger.info("[chatwoot] webhook recebido, mas integração está desabilitada.")

    # Patch futuro:
    # - mapear conversation_id -> Incident
    # - se for mensagem de agente, criar IncidentMessage
    # - se for mudança de status, atualizar incidente, etc.

    return {"status": "ok"}
