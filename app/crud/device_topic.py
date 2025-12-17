# app/crud/device_topic.py
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.device_topic import DeviceTopic
from app.schemas.device_topic import DeviceTopicCreate, DeviceTopicUpdate


class CRUDDeviceTopic(CRUDBase[DeviceTopic, DeviceTopicCreate, DeviceTopicUpdate]):
    async def list_by_device(
        self,
        db: AsyncSession,
        device_id: int,
        only_active: bool = True,
    ) -> List[DeviceTopic]:
        stmt = select(self.model).where(self.model.device_id == device_id)
        if only_active:
            stmt = stmt.where(self.model.is_active.is_(True))
        result = await db.execute(stmt)
        return result.scalars().all()

    async def upsert(
        self,
        db: AsyncSession,
        *,
        device_id: int,
        kind: str,
        topic: str,
        description: Optional[str] = None,
    ) -> DeviceTopic:
        stmt = select(self.model).where(
            self.model.device_id == device_id,
            self.model.kind == kind,
            self.model.topic == topic,
        )
        result = await db.execute(stmt)
        obj = result.scalars().first()
        if obj:
            changed = False
            if description is not None and obj.description != description:
                obj.description = description
                changed = True
            if not obj.is_active:
                obj.is_active = True
                changed = True
            if changed:
                db.add(obj)
            return obj

        create_in = DeviceTopicCreate(
            device_id=device_id,
            kind=kind,
            topic=topic,
            description=description,
        )
        obj = self.model(**create_in.model_dump())
        db.add(obj)
        return obj

    async def mark_all_inactive(self, db: AsyncSession, device_id: int) -> None:
        stmt = (
            update(self.model)
            .where(self.model.device_id == device_id)
            .values(is_active=False)
        )
        await db.execute(stmt)


device_topic = CRUDDeviceTopic(DeviceTopic)
