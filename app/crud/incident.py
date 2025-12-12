from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select, or_, exists
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud.base import CRUDBase
from app.models.incident import Incident
from app.models.device_event import DeviceEvent
from app.schemas.incident import IncidentCreate, IncidentUpdate
from app.models.incident_assignee import incident_assignees          # 👈 NOVO
from app.models.support_group import support_group_members  
from app.models.support_group import SupportGroup
from app.schemas.incident import IncidentCreate, IncidentUpdate


class CRUDIncident(CRUDBase[Incident, IncidentCreate, IncidentUpdate]):
    """
    CRUD especializado para Incident, garantindo que as relações
    assigned_group e assignees sejam sempre carregadas de forma eager,
    evitando lazy-load com AsyncSession (MissingGreenlet).
    """

    async def list_for_user(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Incident]:
        """
        Lista incidentes que estejam:
        - diretamente atribuídos ao usuário (assigned_to_user_id)
        - OU em que o usuário esteja em assignees (tabela incident_assignees)
        - OU atribuídos a um grupo de suporte do qual o usuário é membro.
        """
        # subquery: user está em assignees
        sub_assignee = exists(
            select(1)
            .select_from(incident_assignees)
            .where(
                incident_assignees.c.incident_id == self.model.id,
                incident_assignees.c.user_id == user_id,
            )
        )

        # subquery: user é membro do grupo atribuído ao incidente
        sub_group_member = exists(
            select(1)
            .select_from(support_group_members)
            .where(
                support_group_members.c.support_group_id == self.model.assigned_group_id,
                support_group_members.c.user_id == user_id,
            )
        )

        stmt = (
            self._query_with_relations()
            .where(
                or_(
                    self.model.assigned_to_user_id == user_id,
                    sub_assignee,
                    sub_group_member,
                )
            )
            .order_by(self.model.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        result = await db.execute(stmt)
        return result.scalars().all()

    def _query_with_relations(self):
        """
        Base query que já carrega as relações necessárias para o IncidentRead:
        - assigned_group (+ membros)
        - assignees
        """
        return (
            select(self.model)
            .options(
                selectinload(Incident.assigned_group)
                .selectinload(SupportGroup.members),
                selectinload(Incident.assignees),
            )
        )

    async def get(self, db: AsyncSession, id: int) -> Incident | None:
        stmt = self._query_with_relations().where(self.model.id == id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Incident]:
        stmt = (
            self._query_with_relations()
            .order_by(self.model.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def list_by_device(
        self,
        db: AsyncSession,
        *,
        device_id: int,
        only_open: bool = False,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Incident]:
        stmt = self._query_with_relations().where(self.model.device_id == device_id)

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
        stmt = (
            self._query_with_relations()
            .where(self.model.device_event_id == device_event_id)
        )
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
            self._query_with_relations()
            .where(self.model.status.in_(["OPEN", "IN_PROGRESS"]))
            .order_by(self.model.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def create(
        self,
        db: AsyncSession,
        *,
        obj_in: IncidentCreate | dict,
    ) -> Incident:
        if isinstance(obj_in, dict):
            obj_in_data = obj_in
        else:
            obj_in_data = obj_in.model_dump(exclude_unset=True)

        db_obj = self.model(**obj_in_data)
        db.add(db_obj)
        await db.commit()

        # recarrega com relações
        stmt = self._query_with_relations().where(self.model.id == db_obj.id)
        result = await db.execute(stmt)
        return result.scalar_one()

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
