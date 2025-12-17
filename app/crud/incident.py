# app/crud/incident.py
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud.base import CRUDBase
from app.models.incident import Incident
from app.models.device_event import DeviceEvent
from app.models.incident_assignee import incident_assignees
from app.models.support_group import SupportGroup
from app.models.user import User
from app.schemas.incident import IncidentCreate, IncidentUpdate


class CRUDIncident(CRUDBase[Incident, IncidentCreate, IncidentUpdate]):
    """
    CRUD especializado para Incident, garantindo que as relações
    assigned_group e assignees sejam sempre carregadas de forma eager
    (evitando MissingGreenlet na hora de serializar para o Pydantic).
    """

    # ------------------------------------------------------------------
    # Base query com relações sempre carregadas
    # ------------------------------------------------------------------
    def _query_with_relations(self):
        """
        Sempre que formos devolver Incident para a API,
        usamos ESSA query, com os relacionamentos carregados.
        """
        return (
            select(self.model)
            .options(
                # grupo de suporte + membros
                selectinload(Incident.assigned_group).selectinload(
                    SupportGroup.members
                ),
                # muitos-para-muitos assignees
                selectinload(Incident.assignees),
            )
        )

    # ------------------------------------------------------------------
    # GETs básicos
    # ------------------------------------------------------------------
    async def get(
        self,
        db: AsyncSession,
        id: int,
    ) -> Incident | None:
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
        inc = self.model

        stmt = self._query_with_relations().where(inc.device_id == device_id)

        if only_open:
            stmt = stmt.where(inc.status.in_(["OPEN", "IN_PROGRESS"]))

        stmt = (
            stmt.order_by(inc.created_at.desc())
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
        inc = self.model

        stmt = (
            self._query_with_relations()
            .where(inc.status.in_(["OPEN", "IN_PROGRESS"]))
            .order_by(inc.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    # ------------------------------------------------------------------
    # Visão do operador: incidentes "meus"
    # ------------------------------------------------------------------
    async def list_for_user(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        only_open: bool = False,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Incident]:
        """
        Incidentes visíveis para o usuário:

        - assigned_to_user_id == user_id
        - user presente em assignees (tabela M2M incident_assignees)
        - incident.assigned_group tem o user como membro
        - incidentes gerais: sem grupo e sem responsável direto (todos veem)
        """
        inc = self.model

        # 1) Responsável direto
        cond_direct = inc.assigned_to_user_id == user_id

        # 2) Está em assignees (tabela M2M incident_assignees)
        subq_assignee = (
            select(incident_assignees.c.incident_id)
            .where(incident_assignees.c.user_id == user_id)
        )
        cond_assignee = inc.id.in_(subq_assignee)

        # 3) Incidentes atribuídos a grupos dos quais o user é membro
        #    join usando os relacionamentos ORM (Incident.assigned_group -> SupportGroup.members)
        group_subq = (
            select(inc.id)
            .join(inc.assigned_group)       # Incident.assigned_group
            .join(SupportGroup.members)     # SupportGroup.members -> User
            .where(User.id == user_id)
        )
        cond_group = inc.id.in_(group_subq)

        # 4) Chamados gerais: sem grupo e sem responsável direto
        cond_general = and_(
            inc.assigned_group_id.is_(None),
            inc.assigned_to_user_id.is_(None),
        )

        stmt = self._query_with_relations().where(
            or_(
                cond_direct,
                cond_assignee,
                cond_group,
                cond_general,
            )
        )

        if only_open:
            stmt = stmt.where(inc.status.in_(["OPEN", "IN_PROGRESS"]))

        stmt = (
            stmt.order_by(inc.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        result = await db.execute(stmt)
        return result.scalars().all()

    # ------------------------------------------------------------------
    # CREATE / UPDATE com recarga de relações (anti-MissingGreenlet)
    # ------------------------------------------------------------------
    async def create(
        self,
        db: AsyncSession,
        *,
        obj_in: IncidentCreate | dict,
    ) -> Incident:
        """
        Criação de incidente garantindo que, ao devolver,
        os relacionamentos assigned_group / assignees já estejam carregados
        (evita MissingGreenlet no Pydantic).
        """
        if isinstance(obj_in, dict):
            obj_data = obj_in
        else:
            obj_data = obj_in.model_dump(exclude_unset=True)

        db_obj = self.model(**obj_data)
        db.add(db_obj)
        await db.commit()  # persiste e garante id

        # Recarrega o mesmo incidente com os relacionamentos via selectinload
        stmt = self._query_with_relations().where(self.model.id == db_obj.id)
        result = await db.execute(stmt)
        return result.scalar_one()

    async def update(
        self,
        db: AsyncSession,
        *,
        db_obj: Incident,
        obj_in: IncidentUpdate | dict,
    ) -> Incident:
        """
        Atualização de incidente garantindo que, ao devolver,
        os relacionamentos assigned_group / assignees já estejam carregados.
        """
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(db_obj, field, value)

        await db.commit()

        stmt = self._query_with_relations().where(self.model.id == db_obj.id)
        result = await db.execute(stmt)
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Criação a partir de DeviceEvent
    # ------------------------------------------------------------------
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
        Cria incidente a partir de um DeviceEvent usando IncidentCreate
        e reaproveitando o create() acima.
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

    # ------------------------------------------------------------------
    # Integração Chatwoot: lookup por conversation_id
    # ------------------------------------------------------------------
    async def get_by_chatwoot_conversation(
        self,
        db: AsyncSession,
        *,
        conversation_id: int,
    ) -> Incident | None:
        stmt = (
            self._query_with_relations()
            .where(self.model.chatwoot_conversation_id == conversation_id)
        )
        res = await db.execute(stmt)
        return res.scalar_one_or_none()


incident = CRUDIncident(Incident)
