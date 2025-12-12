# app/services/chatwoot_client.py
from __future__ import annotations

from typing import Optional
import logging

from app.core.config import settings
from app.models.incident import Incident

logger = logging.getLogger(__name__)


class ChatwootClient:
    """
    Cliente de integração com Chatwoot.

    Neste momento é só um stub: não chama HTTP de verdade,
    só verifica se está habilitado e faz log. Depois vamos
    trocar pela implementação real.
    """

    def __init__(self) -> None:
        self.enabled = settings.CHATWOOT_ENABLED
        self.base_url = settings.CHATWOOT_BASE_URL
        self.token = settings.CHATWOOT_API_ACCESS_TOKEN
        self.default_inbox_identifier = settings.CHATWOOT_DEFAULT_INBOX_IDENTIFIER
        self.default_contact_identifier = settings.CHATWOOT_DEFAULT_CONTACT_IDENTIFIER

    def is_configured(self) -> bool:
        return bool(
            self.enabled
            and self.base_url
            and self.token
            and self.default_inbox_identifier
        )

    async def send_incident_notification(
        self,
        incident: Incident,
        incident_url: str,
    ) -> Optional[int]:
        """
        Envia (ou atualiza) uma mensagem no Chatwoot referente a este incidente.

        Por enquanto só faz log. Em patch futuro vamos:
        - criar/usar contact
        - criar/usar conversation
        - enviar message com resumo do incidente
        """

        if not self.is_configured():
            logger.info(
                "[chatwoot] integração desabilitada ou não configurada. "
                "Não enviando notificação para incidente %s.",
                incident.id,
            )
            return incident.chatwoot_conversation_id

        logger.info(
            "[chatwoot] (stub) enviaria notificação para incidente %s (%s) - URL: %s",
            incident.id,
            incident.title,
            incident_url,
        )

        # no futuro vamos retornar o conversation_id real
        return incident.chatwoot_conversation_id
