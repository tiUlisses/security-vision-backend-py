from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.incident import Incident
from app.models.incident_message import IncidentMessage
from app.models.support_group import SupportGroup
from app.services.chatwoot_client import ChatwootClient


def get_chatwoot_client() -> Optional[ChatwootClient]:
    """
    Retorna um client configurado ou None se integração estiver desativada.
    Assim o resto do código pode chamar sem medo (vira no-op se não tiver env).
    """
    if (
        not settings.CHATWOOT_BASE_URL
        or not settings.CHATWOOT_ACCOUNT_ID
        or not settings.CHATWOOT_API_ACCESS_TOKEN
    ):
        return None

    return ChatwootClient(
        base_url=settings.CHATWOOT_BASE_URL,
        account_id=settings.CHATWOOT_ACCOUNT_ID,
        api_access_token=settings.CHATWOOT_API_ACCESS_TOKEN,
    )


async def ensure_conversation_for_incident(
    db: AsyncSession,
    incident: Incident,
) -> Optional[int]:
    """
    Garante que o incidente tenha uma conversa no Chatwoot.
    Se já tiver chatwoot_conversation_id, só retorna.
    """
    client = get_chatwoot_client()
    if not client:
        return None

    if incident.chatwoot_conversation_id:
        return incident.chatwoot_conversation_id

    inbox_id = settings.CHATWOOT_DEFAULT_INBOX_ID
    team_id: int | None = None

    sg: SupportGroup | None = incident.assigned_group
    if sg:
        # aqui eu assumo que você vai gravar no grupo o ID numérico do inbox
        if sg.chatwoot_inbox_identifier:
            try:
                inbox_id = int(sg.chatwoot_inbox_identifier)
            except ValueError:
                # se não for número, cai pro default
                pass
        if sg.chatwoot_team_id:
            team_id = sg.chatwoot_team_id

    if inbox_id is None:
        # sem inbox configurado = não integra
        return None

    # Você pode customizar o "contato" se quiser, por enquanto só um fake contact
    contact = await client.ensure_contact_for_incident(incident)

    conv = await client.create_conversation(
        inbox_id=inbox_id,
        contact_id=contact["id"],
        source_id=str(incident.id),
        additional_attributes={
            "incident_id": incident.id,
            "severity": incident.severity,
            "status": incident.status,
            "device_id": incident.device_id,
        },
    )

    conv_id = conv["id"]
    incident.chatwoot_conversation_id = conv_id
    await db.commit()
    await db.refresh(incident)
    # se tiver team configurado, atribui
    if team_id:
        await client.assign_conversation_to_team(conv_id, team_id=team_id)

    return conv_id


async def send_incident_message_to_chatwoot(
    incident: Incident,
    message: IncidentMessage,
):
    """
    Envia uma mensagem de timeline para o Chatwoot (quando fizer sentido).
    """
    client = get_chatwoot_client()
    if not client:
        return

    if not incident.chatwoot_conversation_id:
        # se por algum motivo não tiver conversa, não faz nada
        return

    # Não faz sentido mandar todas (ex: SYSTEM). Mantemos simples:
    if message.message_type not in ("COMMENT", "MEDIA"):
        return

    content = message.content or ""
    if message.message_type == "MEDIA" and message.media_url:
        # anexa a URL no texto pra, pelo menos, ficar clicável
        content = f"{content}\n\nArquivo: {message.media_url}".strip()

    if not content:
        return

    await client.create_message(
        conversation_id=incident.chatwoot_conversation_id,
        content=content,
        private=False,  # se quiser notas internas, coloca True em alguns casos
        author_name=message.author_name or None,
    )
