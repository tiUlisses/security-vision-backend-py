# app/crud/device.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.device import Device
from app.schemas.device import DeviceCreate, DeviceUpdate


class CRUDDevice(CRUDBase[Device, DeviceCreate, DeviceUpdate]):
    async def get_by_mac(self, db: AsyncSession, mac_address: str) -> Device | None:
        stmt = select(self.model).where(self.model.mac_address == mac_address)
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
    mac_norm = mac_address.upper()
    stmt = select(Device).where(Device.mac_address == mac_norm)
    result = await db.execute(stmt)
    return result.scalars().first()


async def get_or_create_gateway_by_mac(
    db: AsyncSession,
    mac_address: str,
) -> Device:
    mac_norm = mac_address.upper()

    existing = await get_by_mac(db, mac_norm)
    if existing:
        # opcional: garantir que type está correto
        if existing.type != "BLE_GATEWAY":
            existing.type = "BLE_GATEWAY"
            db.add(existing)
            await db.commit()
            await db.refresh(existing)
        return existing

    device = Device(
        name=f"Gateway {mac_norm}",
        code=f"GW_{mac_norm.replace(':', '')}",
        type="BLE_GATEWAY",
        mac_address=mac_norm,
        description="Auto-created from MQTT",
        floor_plan_id=None,
        pos_x=None,
        pos_y=None,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return device


device = CRUDDevice(Device)
