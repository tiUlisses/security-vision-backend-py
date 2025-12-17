"""RTLS Gateways routes.

Nota:
  - O CRUD genérico de devices já possui DELETE em /api/v1/devices/{device_id}.
  - Aqui adicionamos atalhos específicos para gateways e deleção por MAC,
    útil para limpar "sujeira" quando você muda tópico/firmware durante testes.

Importante:
  - Se o gateway continuar publicando no MQTT após você deletar, ele vai ser
    criado novamente automaticamente (porque esse é o comportamento desejado
    do auto-provisioning). Para remover "definitivamente", desligue o gateway
    antes de deletar ou use a rota por MAC para limpar duplicados.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.crud import device as crud_device
from app.schemas import DeviceRead, DeviceStatusRead

from app.models.alert_event import AlertEvent
from app.models.alert_rule import AlertRule
from app.models.collection_log import CollectionLog
from app.models.device import Device
from app.models.device_event import DeviceEvent
from app.models.device_topic import DeviceTopic
from app.models.incident import Incident
from app.utils.mac import candidate_macs

from .base import _build_device_status_list  # reaproveita a lógica de status

router = APIRouter()


async def _purge_gateway_related_rows(db: AsyncSession, device_id: int) -> None:
    """Remove linhas relacionadas a um gateway.

    Mesmo que existam ON DELETE CASCADE / delete-orphan, isso torna a remoção
    mais "à prova de ambiente" (migrações antigas, etc) e ajuda a limpar a base
    quando você está testando e quer zerar rastros.
    """

    await db.execute(delete(CollectionLog).where(CollectionLog.device_id == device_id))
    await db.execute(delete(DeviceTopic).where(DeviceTopic.device_id == device_id))
    await db.execute(delete(DeviceEvent).where(DeviceEvent.device_id == device_id))
    await db.execute(delete(Incident).where(Incident.device_id == device_id))

    # Em teste normalmente é desejável limpar histórico de alertas também:
    await db.execute(delete(AlertRule).where(AlertRule.device_id == device_id))
    await db.execute(delete(AlertEvent).where(AlertEvent.device_id == device_id))


@router.get("/", response_model=List[DeviceRead])
async def list_gateways(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db_session),
):
    """Lista apenas devices do tipo BLE_GATEWAY."""
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
    """Status apenas dos gateways RTLS."""
    devices = await crud_device.get_multi_by_type(db, type_="BLE_GATEWAY")
    return await _build_device_status_list(db, devices, only_gateways=False)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gateway(
    device_id: int,
    purge_related: bool = Query(
        True,
        description=(
            "Se true, remove também logs/tópicos/eventos relacionados ao gateway antes de deletar. "
            "Útil para limpar a base durante testes."
        ),
    ),
    db: AsyncSession = Depends(get_db_session),
):
    """Deleta um gateway por ID (Device.id)."""

    db_obj = await crud_device.get(db, id=device_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Gateway not found")

    if getattr(db_obj, "type", None) != "BLE_GATEWAY":
        raise HTTPException(status_code=400, detail="Device is not a BLE_GATEWAY")

    if purge_related:
        await _purge_gateway_related_rows(db, device_id=device_id)

    await db.delete(db_obj)
    await db.commit()
    return None


@router.delete("/by-mac/{mac}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gateway_by_mac(
    mac: str,
    delete_all_matches: bool = Query(
        True,
        description=(
            "Se true, remove todos os gateways que tiverem mac_address em qualquer "
            "formato equivalente (com/sem ':', '-', etc). Útil para limpar duplicados."
        ),
    ),
    purge_related: bool = Query(
        True,
        description=(
            "Se true, remove também logs/tópicos/eventos relacionados a cada gateway removido. "
            "Útil para limpar a base durante testes."
        ),
    ),
    db: AsyncSession = Depends(get_db_session),
):
    """Deleta gateway(s) por MAC (limpa duplicados por formatação)."""

    cands = list(candidate_macs(mac))
    if not cands:
        raise HTTPException(status_code=400, detail="Invalid MAC")

    stmt = select(Device).where(
        Device.type == "BLE_GATEWAY",
        Device.mac_address.in_(cands),
    )
    res = await db.execute(stmt)
    matches = list(res.scalars().all())
    if not matches:
        raise HTTPException(status_code=404, detail="Gateway not found")

    if not delete_all_matches:
        matches = matches[:1]

    for dev in matches:
        if purge_related:
            await _purge_gateway_related_rows(db, device_id=dev.id)
        await db.delete(dev)

    await db.commit()
    return None
