# app/crud/incident.py
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.incident import Incident
from app.models.device_event import DeviceEvent
from app.schemas.incident import IncidentCreate, IncidentUpdate


class CRUDIncident(CRUDBase[Incident, IncidentCreate, IncidentUpdate]):
    async def list_by_device(
        self,
        db: AsyncSession,
        *,
        device_id: int,
        only_open: bool = False,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Incident]:
        stmt = select(self.model).where(self.model.device_id == device_id)

        if only_open:
            stmt = stmt.where(self.model.status.in_(["OPEN", "IN_PROGRESS"]))

        stmt = (
            stmt.order_by(self.model.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_device_event(
        self,
        db: AsyncSession,
        *,
        device_event_id: int,
    ) -> Incident | None:
        stmt = select(Incident).where(Incident.device_event_id == device_event_id)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()
        
    async def list_open(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Incident]:
        stmt = (
            select(self.model)
            .where(self.model.status.in_(["OPEN", "IN_PROGRESS"]))
            .order_by(self.model.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def create_from_device_event(
        self,
        db: AsyncSession,
        *,
        device_event: DeviceEvent,
        title: str,
        description: Optional[str] = None,
        severity: str = "MEDIUM",
        kind: str = "CAMERA_ISSUE",
    ) -> Incident:
        """
        Helper para criar incidente diretamente a partir de um DeviceEvent.
        Usado, por exemplo, quando o operador abre o modal de evento e
        clica em "Criar incidente".
        """
        incident_in = IncidentCreate(
            device_id=device_event.device_id,
            device_event_id=device_event.id,
            title=title,
            description=description,
            severity=severity,
            kind=kind,
        )
        return await self.create(db, obj_in=incident_in)


incident = CRUDIncident(Incident)
