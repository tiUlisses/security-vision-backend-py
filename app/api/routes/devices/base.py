# app/api/routes/devices/base.py
from datetime import datetime, timezone
from typing import List
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.alert_engine import handle_gateway_status_transition
from app.services.webhook_dispatcher import dispatch_generic_webhook
from app.api.deps import get_db_session
from app.services.cambus_publisher import (
    publish_camera_info_from_device,
    disable_cambus_topics_for_device,  # 👈 importante p/ desabilitar tópicos antigos
)
from app.core.config import settings
from app.crud import device as crud_device
from app.crud import device_topic as crud_device_topic
from app.schemas import (
    DeviceCreate,
    DeviceRead,
    DeviceUpdate,
    DeviceStatusRead,
    DevicePositionUpdate,
    DeviceTopicRead,
)

router = APIRouter()
logger = logging.getLogger("app.api.devices")


def _compute_is_online(last_seen_at: datetime | None) -> bool:
    if last_seen_at is None:
        return False

    # Sempre compara em UTC
    now = datetime.now(timezone.utc)

    if last_seen_at.tzinfo is None:
        # Tratamos last_seen_at como UTC naive
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
    else:
        last_seen_at = last_seen_at.astimezone(timezone.utc)

    delta = now - last_seen_at
    return delta.total_seconds() <= settings.DEVICE_OFFLINE_THRESHOLD_SECONDS


async def _build_device_status_list(
    db: AsyncSession,
    devices,
    only_gateways: bool = False,
) -> List[DeviceStatusRead]:
    """
    Monta a lista de status (online/offline) para qualquer conjunto de devices.

    - Se only_gateways=True, filtra por type == BLE_GATEWAY.
    - AlertEngine só é chamado para gateways (BLE_GATEWAY).
    """
    result: list[DeviceStatusRead] = []

    for dev in devices:
        if only_gateways and getattr(dev, "type", None) != "BLE_GATEWAY":
            continue

        is_online = _compute_is_online(dev.last_seen_at)

        # Garante que só gateways disparam a lógica de alerta
        if getattr(dev, "type", None) == "BLE_GATEWAY":
            await handle_gateway_status_transition(
                db,
                device=dev,
                is_online_now=is_online,
            )

        result.append(
            DeviceStatusRead(
                id=dev.id,
                name=dev.name,
                type=getattr(dev, "type", ""),
                mac_address=getattr(dev, "mac_address", None),
                ip_address=getattr(dev, "ip_address", None),
                building_id=getattr(dev, "building_id", None),
                floor_id=getattr(dev, "floor_id", None),
                last_seen_at=dev.last_seen_at,
                is_online=is_online,
            )
        )

    return result


@router.get("/", response_model=List[DeviceRead])
async def list_devices(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Lista genérica de devices (gateways, câmeras, controladores, etc).
    """
    return await crud_device.get_multi(db, skip=skip, limit=limit)


@router.post(
    "/",
    response_model=DeviceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_device(
    device_in: DeviceCreate,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Cria um device genérico.
    O tipo (type) vem do payload: BLE_GATEWAY, CAMERA, ACCESS_CONTROLLER...
    """
    device = await crud_device.create(db, device_in)

    # 🔔 Webhook: DEVICE_CREATED
    await dispatch_generic_webhook(
        db,
        event_type="DEVICE_CREATED",
        payload={
            "device_id": device.id,
            "name": device.name,
            "type": device.type,
            "mac_address": device.mac_address,
            "floor_plan_id": device.floor_plan_id,
            "created_at": device.created_at.isoformat()
            if getattr(device, "created_at", None)
            else None,
        },
    )

    # Se for CAMERA, publica /info pro cam-bus
    try:
        await publish_camera_info_from_device(db, device)
    except Exception as exc:
        logger.exception(
            "[devices] erro ao publicar /info para camera id=%s: %s",
            device.id,
            exc,
        )

    return device


# ⚠️ IMPORTANTE: /status VEM ANTES DE "/{device_id}"
@router.get("/status", response_model=List[DeviceStatusRead])
async def list_device_status(
    only_gateways: bool = Query(
        False,
        description="Se true, retorna apenas devices do tipo BLE_GATEWAY",
    ),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Retorna o status ONLINE/OFFLINE de cada device, baseado no last_seen_at.

    - Se only_gateways=True, limita a BLE_GATEWAY.
    - AlertEngine só é disparado para gateways.
    """
    devices = await crud_device.get_multi(db)
    return await _build_device_status_list(db, devices, only_gateways=only_gateways)


@router.get("/{device_id}", response_model=DeviceRead)
async def get_device(
    device_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_device.get(db, id=device_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Device not found")
    return db_obj


@router.put("/{device_id}", response_model=DeviceRead)
async def update_device(
    device_id: int,
    device_in: DeviceUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_device.get(db, id=device_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Device not found")

    # Guarda estado antigo para detectar mudança de path MQTT (câmeras)
    old_building_id = getattr(db_obj, "building_id", None)
    old_floor_id = getattr(db_obj, "floor_id", None)
    old_code = getattr(db_obj, "code", None)
    old_type = getattr(db_obj, "type", None)

    updated = await crud_device.update(db, db_obj, device_in)

    # 🔔 Webhook: DEVICE_UPDATED
    await dispatch_generic_webhook(
        db,
        event_type="DEVICE_UPDATED",
        payload={
            "device_id": updated.id,
            "name": updated.name,
            "type": updated.type,
            "mac_address": updated.mac_address,
            "floor_plan_id": updated.floor_plan_id,
            "updated_at": updated.updated_at.isoformat()
            if getattr(updated, "updated_at", None)
            else None,
        },
    )

    # Se for CAMERA, precisamos cuidar do ciclo /info do cam-bus
    if getattr(updated, "type", None) == "CAMERA":
        new_building_id = getattr(updated, "building_id", None)
        new_floor_id = getattr(updated, "floor_id", None)
        new_code = getattr(updated, "code", None)

        topology_changed = (
            old_type != "CAMERA"
            or old_building_id != new_building_id
            or old_floor_id != new_floor_id
            or old_code != new_code
        )

        # Se mudou path (prédio/andar/code) ou virou CAMERA, desabilita tópicos antigos
        if topology_changed:
            try:
                await disable_cambus_topics_for_device(db, device_id=updated.id)
            except Exception as exc:
                logger.exception(
                    "[devices] erro ao desabilitar tópicos cam-bus (update) device_id=%s: %s",
                    updated.id,
                    exc,
                )

        # Sempre republica /info com estado atual
        try:
            await publish_camera_info_from_device(db, updated)
        except Exception as exc:
            logger.exception(
                "[devices] erro ao publicar /info (update) para camera id=%s: %s",
                updated.id,
                exc,
            )

    return updated


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Deleta um device genérico.
    Se for CAMERA, desabilita os tópicos do cam-bus antes de remover.
    """
    db_obj = await crud_device.get(db, id=device_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Device not found")

    # Se for câmera, desabilita /info + /events no broker (enabled=false + inativo)
    if getattr(db_obj, "type", None) == "CAMERA":
        try:
            await disable_cambus_topics_for_device(db, device_id=db_obj.id)
        except Exception as exc:
            logger.exception(
                "[devices] erro ao desabilitar tópicos cam-bus (delete) device_id=%s: %s",
                db_obj.id,
                exc,
            )

    deleted = await crud_device.remove(db, id=device_id)
    if not deleted:
        # segurança extra
        raise HTTPException(status_code=404, detail="Device not found")

    # 🔔 Webhook: DEVICE_DELETED
    await dispatch_generic_webhook(
        db,
        event_type="DEVICE_DELETED",
        payload={
            "device_id": deleted.id,
            "name": deleted.name,
            "type": deleted.type,
            "mac_address": deleted.mac_address,
            "floor_plan_id": deleted.floor_plan_id,
        },
    )

    return None


@router.patch("/{device_id}/position", response_model=DeviceRead)
async def update_device_position(
    device_id: int,
    position_in: DevicePositionUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_device.get(db, id=device_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Device not found")

    update_data = position_in.dict(exclude_unset=True)
    updated = await crud_device.update(db, db_obj, update_data)

    # 🔔 Webhook: DEVICE_POSITION_UPDATED
    await dispatch_generic_webhook(
        db,
        event_type="DEVICE_POSITION_UPDATED",
        payload={
            "device_id": updated.id,
            "name": updated.name,
            "mac_address": updated.mac_address,
            "floor_plan_id": updated.floor_plan_id,
            "pos_x": updated.pos_x,
            "pos_y": updated.pos_y,
        },
    )

    # Se for CAMERA, atualizar /info (não muda path, mas muda floor_plan/pos_x/pos_y)
    if getattr(updated, "type", None) == "CAMERA":
        try:
            await publish_camera_info_from_device(db, updated)
        except Exception as exc:
            logger.exception(
                "[devices] erro ao publicar /info (position) para camera id=%s: %s",
                updated.id,
                exc,
            )

    return updated


@router.get(
    "/{device_id}/topics",
    response_model=List[DeviceTopicRead],
)
async def list_device_topics(
    device_id: int,
    only_active: bool = Query(
        True,
        description="Se true, retorna apenas tópicos ativos (is_active = true).",
    ),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Lista os tópicos MQTT associados a um device (tabela device_topics).

    Serve pra validar:
    - em qual path MQTT a câmera/gateway está hoje;
    - quais tópicos antigos ficaram inativos após mover prédio/andar/código.
    """
    db_obj = await crud_device.get(db, id=device_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Device not found")

    topics = await crud_device_topic.list_by_device(
        db,
        device_id=device_id,
        only_active=only_active,
    )
    return topics
