# app/crud/device_event.py
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.device_event import DeviceEvent


class CRUDDeviceEvent(CRUDBase[DeviceEvent, None, None]):
    async def list_by_device(
        self,
        db: AsyncSession,
        device_id: int,
        limit: int = 100,
    ) -> List[DeviceEvent]:
        stmt = (
            select(DeviceEvent)
            .where(DeviceEvent.device_id == device_id)
            .order_by(DeviceEvent.occurred_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()


device_event = CRUDDeviceEvent(DeviceEvent)
