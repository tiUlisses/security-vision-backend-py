# app/crud/device.py
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.device import Device
from app.schemas.device import DeviceCreate, DeviceUpdate
from app.utils.mac import candidate_macs, normalize_mac


class CRUDDevice(CRUDBase[Device, DeviceCreate, DeviceUpdate]):
    async def get_by_mac(self, db: AsyncSession, mac_address: str) -> Device | None:
        cands = candidate_macs(mac_address)
        if not cands:
            return None
        stmt = select(self.model).where(self.model.mac_address.in_(list(cands)))
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_by_code(self, db: AsyncSession, code: str) -> Device | None:
        stmt = select(self.model).where(self.model.code == code)
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_multi_by_type(
        self,
        db: AsyncSession,
        type_: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Device]:
        stmt = (
            select(self.model)
            .where(self.model.type == type_)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()


async def get_by_mac(db: AsyncSession, mac_address: str) -> Device | None:
    """Compat helper usado em serviços. Tolerante a formatos."""
    cands = candidate_macs(mac_address)
    if not cands:
        return None
    stmt = select(Device).where(Device.mac_address.in_(list(cands)))
    result = await db.execute(stmt)
    return result.scalars().first()


async def get_or_create_gateway_by_mac(
    db: AsyncSession,
    mac_address: str,
    *,
    building_id: Optional[int] = None,
    floor_id: Optional[int] = None,
) -> Device:
    """Garante a existência de um Device BLE_GATEWAY pelo MAC.

    - Normaliza MAC (preferindo 12-hex uppercase)
    - Se já existir: garante type=BLE_GATEWAY e aplica building_id/floor_id se vierem
    - Se não existir: cria com building_id/floor_id
    """
    mac_norm = normalize_mac(mac_address) or str(mac_address).strip().upper()

    existing = await get_by_mac(db, mac_norm)
    if existing:
        changed = False
        if existing.type != "BLE_GATEWAY":
            existing.type = "BLE_GATEWAY"
            changed = True

        if building_id is not None and existing.building_id != building_id:
            existing.building_id = building_id
            changed = True

        # floor_id só faz sentido se for coerente com o prédio, mas aqui aceitamos
        # e deixamos a integridade referencial do DB garantir.
        if floor_id is not None and existing.floor_id != floor_id:
            existing.floor_id = floor_id
            changed = True

        if changed:
            db.add(existing)
            await db.commit()
            await db.refresh(existing)

        return existing

    device = Device(
        name=f"Gateway {mac_norm}",
        code=f"GW_{mac_norm}",
        type="BLE_GATEWAY",
        mac_address=mac_norm,
        description="Auto-created from MQTT",
        floor_plan_id=None,
        building_id=building_id,
        floor_id=floor_id,
        pos_x=None,
        pos_y=None,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return device


device = CRUDDevice(Device)
