# app/api/routes/devices/cameras.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_db_session
from app.core.config import settings
from app.crud import device as crud_device
from app.crud import device_event as crud_device_event
from app.schemas import (
    DeviceRead,
    DeviceStatusRead,
    CameraCreate,
    CameraUpdate,
    DeviceCreate,
    DeviceUpdate,
    DeviceEventRead,
)
from app.services.webhook_dispatcher import dispatch_generic_webhook
from app.services.cambus_publisher import (
    publish_camera_info_from_device,
    disable_cambus_topics_for_device,
)
from .base import _build_device_status_list

router = APIRouter()


@router.get("/", response_model=List[DeviceRead])
async def list_cameras(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Lista apenas devices do tipo CAMERA.
    """
    return await crud_device.get_multi_by_type(
        db,
        type_="CAMERA",
        skip=skip,
        limit=limit,
    )


@router.get("/status", response_model=List[DeviceStatusRead])
async def list_camera_status(
    db: AsyncSession = Depends(get_db_session),
):
    """
    Status apenas das câmeras.
    (por enquanto só lê last_seen_at; depois podemos plugar alerta de câmera offline.)
    """
    devices = await crud_device.get_multi_by_type(db, type_="CAMERA")
    # AlertEngine, por enquanto, só dispara pra gateways (controlado no helper)
    return await _build_device_status_list(db, devices, only_gateways=False)


@router.post(
    "/",
    response_model=DeviceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_camera(
    camera_in: CameraCreate,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Cria uma câmera (Device.type = 'CAMERA'), valida 'code' único
    e já publica o /info + registra tópicos pro cam-bus.
    """
    # 1) valida code único ANTES de tentar inserir
    code = (camera_in.code or "").strip()
    if code:
        existing = await crud_device.get_by_code(db, code)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Já existe um device com code='{code}'.",
            )

    # 2) monta o DeviceCreate com type="CAMERA"
    data = camera_in.dict(exclude_unset=True)
    data["type"] = "CAMERA"
    data.setdefault("floor_plan_id", None)
    data.setdefault("mac_address", None)
    data.setdefault("description", None)
    data.setdefault("pos_x", None)
    data.setdefault("pos_y", None)

    # shard padrão se não vier
    data.setdefault("shard", settings.CAMBUS_DEFAULT_SHARD)

    device_create = DeviceCreate(**data)

    try:
        device = await crud_device.create(db, device_create)
    except IntegrityError as exc:
        # Fallback se outro índice único explodir (ex: code ou mac)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Violação de unicidade ao criar device (verifique code/mac_address).",
        ) from exc

    # Webhook opcional
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

    # Publica /info para o cam-bus + registra device_topics
    await publish_camera_info_from_device(db, device)

    return device





@router.get("/{camera_id}/events", response_model=List[DeviceEventRead])
async def list_device_events(
    camera_id: int,
    limit: int = Query(100, le=1000),
    db: AsyncSession = Depends(get_db_session),
):
    # garante que a câmera existe e é do tipo CAMERA
    db_obj = await crud_device.get(db, id=camera_id)
    if not db_obj or db_obj.type != "CAMERA":
        raise HTTPException(status_code=404, detail="Camera not found")

    events = await crud_device_event.list_by_device(
        db,
        device_id=camera_id,
        limit=limit,
    )
    return events

@router.put("/{camera_id}", response_model=DeviceRead)
async def update_camera(
    camera_id: int,
    camera_in: CameraUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_device.get(db, id=camera_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Camera not found")

    if db_obj.type != "CAMERA":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device não é do tipo CAMERA.",
        )

    # --- snapshot do estado antigo, pra saber se muda o "endereço" MQTT ---
    old_building_id = getattr(db_obj, "building_id", None)
    old_floor_id = getattr(db_obj, "floor_id", None)
    old_code = getattr(db_obj, "code", None)

    # Usa diretamente o CameraUpdate (que já tem analytics)
    data = camera_in.dict(exclude_unset=True)

    # Sempre CAMERA
    data["type"] = "CAMERA"

    # Mantém ou define shard padrão
    current_shard = getattr(db_obj, "shard", None) or settings.CAMBUS_DEFAULT_SHARD
    data.setdefault("shard", current_shard)

    # 👇 Aqui a diferença: passa um dict pro CRUD, não recria DeviceUpdate
    updated = await crud_device.update(db, db_obj, data)

    # Webhook
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

    # --- detecta se o "path" MQTT mudou (prédio/andar/code) ---
    topology_changed = (
        old_building_id != getattr(updated, "building_id", None)
        or old_floor_id != getattr(updated, "floor_id", None)
        or old_code != getattr(updated, "code", None)
    )

    # Se mudou o path, desabilita tópicos antigos (enabled=false nos /info antigos
    # e marca device_topics como inativos)
    if topology_changed:
        await disable_cambus_topics_for_device(db, device_id=updated.id)

    # Sempre republica /info com o estado atual (incluindo analytics novos)
    await publish_camera_info_from_device(db, updated)

    return updated


