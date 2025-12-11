# app/crud/device_event.py
from typing import List, Any, Dict

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

    async def create(
        self,
        db: AsyncSession,
        *,
        obj_in: Dict[str, Any],
    ) -> DeviceEvent:
        db_event = await super().create(db, obj_in=obj_in)

        try:
            from app.services.incident_auto_rules import apply_incident_rules_for_event

            print(f"[device_event] DeviceEvent criado id={db_event.id}, disparando avaliação de regras...")
            await apply_incident_rules_for_event(db, event=db_event)
        except Exception as exc:
            print(
                f"[device_event] Erro ao aplicar regras de incidente "
                f"para DeviceEvent id={db_event.id}: {exc}"
            )

        return db_event


device_event = CRUDDeviceEvent(DeviceEvent)
