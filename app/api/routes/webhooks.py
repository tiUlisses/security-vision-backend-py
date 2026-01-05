from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.crud import webhook_subscription as crud_webhook
from app.schemas.webhook import (
    WebhookSubscriptionCreate,
    WebhookSubscriptionRead,
    WebhookSubscriptionUpdate,
    WebhookEventTypeMeta,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# Catálogo de tipos de evento de webhook
# ---------------------------------------------------------------------------

WEBHOOK_EVENT_TYPES: List[WebhookEventTypeMeta] = [
    # CRUD – prédios
    WebhookEventTypeMeta(
        event_type="BUILDING_CREATED",
        label="Criação de prédio",
        description="Disparado quando um prédio é criado via API.",
        sample_payload={
            "event_type": "BUILDING_CREATED",
            "occurred_at": "2024-01-01T12:34:56Z",
            "data": {
                "building": {
                    "id": 1,
                    "name": "Edifício HowBE",
                    "description": "Prédio principal",
                    "created_at": "2024-01-01T12:34:56Z",
                }
            },
        },
    ),
    # CRUD – devices / gateways
    WebhookEventTypeMeta(
        event_type="DEVICE_CREATED",
        label="Criação de gateway/dispositivo",
        description="Disparado quando um device (ex: gateway BLE) é criado.",
        sample_payload={
            "event_type": "DEVICE_CREATED",
            "occurred_at": "2024-01-01T12:34:56Z",
            "data": {
                "device": {
                    "id": 10,
                    "name": "Gateway Entrada",
                    "type": "BLE_GATEWAY",
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "floor_plan_id": 3,
                    "pos_x": 0.25,
                    "pos_y": 0.75,
                    "created_at": "2024-01-01T12:34:56Z",
                }
            },
        },
    ),
    # CRUD – pessoas
    WebhookEventTypeMeta(
        event_type="PERSON_CREATED",
        label="Criação de pessoa",
        description="Disparado quando uma pessoa é cadastrada.",
        sample_payload={
            "event_type": "PERSON_CREATED",
            "occurred_at": "2024-01-01T12:34:56Z",
            "data": {
                "person": {
                    "id": 42,
                    "full_name": "Fulano de Tal",
                    "document": "000.000.000-00",
                    "created_at": "2024-01-01T12:34:56Z",
                }
            },
        },
    ),
    # CRUD – tags
    WebhookEventTypeMeta(
        event_type="TAG_CREATED",
        label="Criação de TAG",
        description="Disparado quando uma TAG BLE é cadastrada.",
        sample_payload={
            "event_type": "TAG_CREATED",
            "occurred_at": "2024-01-01T12:34:56Z",
            "data": {
                "tag": {
                    "id": 7,
                    "code": "TAG-0007",
                    "mac_address": "AA:BB:CC:DD:EE:99",
                    "person_id": 42,
                    "created_at": "2024-01-01T12:34:56Z",
                }
            },
        },
    ),
    # Incidentes – criação
    WebhookEventTypeMeta(
        event_type="INCIDENT_CREATED",
        label="Criação de incidente",
        description="Disparado quando um incidente é criado.",
        sample_payload={
            "event_type": "INCIDENT_CREATED",
            "occurred_at": "2024-01-01T12:34:56Z",
            "data": {
                "incident": {
                    "id": 501,
                    "device_id": 10,
                    "device_event_id": 987,
                    "kind": "CAMERA_EVENT",
                    "tenant": "ACME",
                    "status": "OPEN",
                    "severity": "MEDIUM",
                    "title": "Pessoa não autorizada na área restrita",
                    "description": "Detecção pela câmera da recepção.",
                    "sla_minutes": 60,
                    "due_at": "2024-01-01T13:34:56Z",
                    "assigned_group_id": 3,
                    "assigned_to_user_id": 12,
                    "created_at": "2024-01-01T12:34:56Z",
                    "updated_at": "2024-01-01T12:34:56Z",
                }
            },
        },
    ),
    # Incidentes – alteração de status
    WebhookEventTypeMeta(
        event_type="INCIDENT_STATUS_CHANGED",
        label="Status do incidente alterado",
        description="Disparado quando o status do incidente muda.",
        sample_payload={
            "event_type": "INCIDENT_STATUS_CHANGED",
            "occurred_at": "2024-01-01T12:50:00Z",
            "data": {
                "incident": {
                    "id": 501,
                    "status": "IN_PROGRESS",
                    "severity": "MEDIUM",
                    "title": "Pessoa não autorizada na área restrita",
                    "updated_at": "2024-01-01T12:50:00Z",
                },
                "previous_status": "OPEN",
            },
        },
    ),
    # Incidentes – reabertura
    WebhookEventTypeMeta(
        event_type="INCIDENT_REOPENED",
        label="Reabertura de incidente",
        description="Disparado quando um incidente fechado é reaberto.",
        sample_payload={
            "event_type": "INCIDENT_REOPENED",
            "occurred_at": "2024-01-01T13:10:00Z",
            "data": {
                "incident": {
                    "id": 501,
                    "status": "OPEN",
                    "severity": "MEDIUM",
                    "title": "Pessoa não autorizada na área restrita",
                    "closed_at": None,
                    "updated_at": "2024-01-01T13:10:00Z",
                },
                "previous_status": "CLOSED",
            },
        },
    ),
    # Incidentes – mensagem criada
    WebhookEventTypeMeta(
        event_type="INCIDENT_MESSAGE_CREATED",
        label="Mensagem do incidente criada",
        description="Disparado quando uma mensagem é adicionada na timeline do incidente.",
        sample_payload={
            "event_type": "INCIDENT_MESSAGE_CREATED",
            "occurred_at": "2024-01-01T13:15:00Z",
            "data": {
                "incident_id": 501,
                "message": {
                    "id": 901,
                    "message_type": "TEXT",
                    "content": "Equipe em deslocamento para verificação.",
                    "author_name": "Operador",
                    "created_at": "2024-01-01T13:15:00Z",
                },
            },
        },
    ),
    # Alertas – área proibida
    WebhookEventTypeMeta(
        event_type="FORBIDDEN_SECTOR",
        label="Alerta: setor proibido",
        description="Disparado quando alguém entra em um gateway marcado como setor proibido.",
        sample_payload={
            "event_type": "FORBIDDEN_SECTOR",
            "triggered_at": "2024-01-01T12:34:56Z",
            "alert": {
                "id": 100,
                "rule_id": 1,
                "person_id": 42,
                "tag_id": 7,
                "device_id": 10,
                "message": "Entrada em setor proibido: Fulano no gateway 'Entrada'.",
                "location": {
                    "building_id": 1,
                    "building_name": "Edifício HowBE",
                    "floor_id": 1,
                    "floor_name": "1º andar",
                    "floor_plan_id": 3,
                    "floor_plan_name": "Mapa Recepção",
                },
                "started_at": "2024-01-01T12:34:56Z",
                "last_seen_at": "2024-01-01T12:35:10Z",
                "ended_at": None,
                "is_open": True,
            },
        },
    ),
    # Alertas – dwell time
    WebhookEventTypeMeta(
        event_type="DWELL_TIME",
        label="Alerta: tempo de permanência",
        description="Disparado quando o tempo de permanência atinge o limite configurado na regra.",
        sample_payload={
            "event_type": "DWELL_TIME",
            "triggered_at": "2024-01-01T12:34:56Z",
            "alert": {
                "id": 101,
                "rule_id": 2,
                "person_id": 42,
                "tag_id": 7,
                "device_id": 10,
                "message": "Fulano está há 600s no dispositivo Gateway Entrada (limite 600s).",
                "started_at": "2024-01-01T12:24:56Z",
                "last_seen_at": "2024-01-01T12:34:56Z",
                "ended_at": None,
                "is_open": True,
                "dwell_seconds": 600,
                "max_dwell_seconds": 600,
            },
        },
    ),
    # Alertas – gateway offline
    WebhookEventTypeMeta(
        event_type="GATEWAY_OFFLINE",
        label="Alerta: gateway offline",
        description="Disparado quando um gateway é considerado offline pelo motor de alertas.",
        sample_payload={
            "event_type": "GATEWAY_OFFLINE",
            "triggered_at": "2024-01-01T12:35:00Z",
            "alert": {
                "id": 200,
                "device_id": 10,
                "device_name": "Gateway Entrada",
                "building_name": "Edifício HowBE",
                "floor_plan_name": "Mapa Recepção",
                "offline_seconds": 120,
                "message": "Gateway 'Gateway Entrada' está offline há 120s.",
            },
        },
    ),
    # Alertas – gateway online novamente
    WebhookEventTypeMeta(
        event_type="GATEWAY_ONLINE",
        label="Alerta: gateway online",
        description="Disparado quando um gateway retorna ao estado online após ficar offline.",
        sample_payload={
            "event_type": "GATEWAY_ONLINE",
            "triggered_at": "2024-01-01T12:40:00Z",
            "alert": {
                "id": 201,
                "device_id": 10,
                "device_name": "Gateway Entrada",
                "building_name": "Edifício HowBE",
                "floor_plan_name": "Mapa Recepção",
                "message": "Gateway 'Gateway Entrada' voltou a ficar online.",
            },
        },
    ),
]


@router.get("/event-types", response_model=List[WebhookEventTypeMeta])
async def list_webhook_event_types():
    """
    Retorna os tipos de evento que o backend suporta para webhooks,
    com label, descrição e um sample_payload para o frontend montar o preview.
    """
    return WEBHOOK_EVENT_TYPES


# ---------------------------------------------------------------------------
# CRUD de subscriptions (já existia, mantido)
# ---------------------------------------------------------------------------


@router.get("/", response_model=List[WebhookSubscriptionRead])
async def list_webhooks(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db_session),
):
    return await crud_webhook.get_multi(db, skip=skip, limit=limit)


@router.post(
    "/",
    response_model=WebhookSubscriptionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook(
    webhook_in: WebhookSubscriptionCreate,
    db: AsyncSession = Depends(get_db_session),
):
    return await crud_webhook.create(db, webhook_in)


@router.get("/{webhook_id}", response_model=WebhookSubscriptionRead)
async def get_webhook(
    webhook_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_webhook.get(db, id=webhook_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return db_obj


@router.put("/{webhook_id}", response_model=WebhookSubscriptionRead)
async def update_webhook(
    webhook_id: int,
    webhook_in: WebhookSubscriptionUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_webhook.get(db, id=webhook_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return await crud_webhook.update(db, db_obj, webhook_in)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    deleted = await crud_webhook.remove(db, id=webhook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return None
