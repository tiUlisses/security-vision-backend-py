# app/api/routes/devices/gateways.py
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.crud import device as crud_device
from app.schemas import DeviceRead, DeviceStatusRead

from .base import _build_device_status_list  # reaproveita a lógica de status

router = APIRouter()


@router.get("/", response_model=List[DeviceRead])
async def list_gateways(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Lista apenas devices do tipo BLE_GATEWAY.
    """
    return await crud_device.get_multi_by_type(
        db,
        type_="BLE_GATEWAY",
        skip=skip,
        limit=limit,
    )


@router.get("/status", response_model=List[DeviceStatusRead])
async def list_gateway_status(
    db: AsyncSession = Depends(get_db_session),
):
    """
    Status apenas dos gateways RTLS.
    """
    devices = await crud_device.get_multi_by_type(db, type_="BLE_GATEWAY")
    # aqui não precisamos do filtro only_gateways, já vem só gateway
    return await _build_device_status_list(db, devices, only_gateways=False)
