# app/crud/support_group.py
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud.base import CRUDBase
from app.models.support_group import SupportGroup
from app.models.user import User
from app.schemas.support_group import SupportGroupCreate, SupportGroupUpdate


class CRUDSupportGroup(CRUDBase[SupportGroup, SupportGroupCreate, SupportGroupUpdate]):
    async def list_all(
        self,
        db: AsyncSession,
    ) -> List[SupportGroup]:
        # 🔹 já carrega os membros com selectinload para evitar lazy-load na resposta
        stmt = (
            select(self.model)
            .options(selectinload(self.model.members))
            .order_by(self.model.name.asc())
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_name(
        self,
        db: AsyncSession,
        *,
        name: str,
    ) -> Optional[SupportGroup]:
        stmt = select(self.model).where(self.model.name == name)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_members_by_ids(
        self,
        db: AsyncSession,
        member_ids: Optional[list[int]],
    ) -> List[User]:
        if not member_ids:
            return []

        stmt = select(User).where(User.id.in_(member_ids))
        result = await db.execute(stmt)
        return result.scalars().all()

    async def create_with_members(
        self,
        db: AsyncSession,
        *,
        obj_in: SupportGroupCreate,
    ) -> SupportGroup:
        # 1) busca os usuários membros
        members = await self._get_members_by_ids(db, obj_in.member_ids)

        # 2) cria o grupo em memória com os membros
        group = SupportGroup(
            name=obj_in.name,
            description=obj_in.description,
            is_active=obj_in.is_active,
            default_sla_minutes=obj_in.default_sla_minutes,
            chatwoot_inbox_identifier=obj_in.chatwoot_inbox_identifier,
            chatwoot_team_id=obj_in.chatwoot_team_id,
            members=members,
        )

        db.add(group)
        # força flush para ter o ID antes da nova query
        await db.flush()
        group_id = group.id

        # commita para gravar o grupo e a tabela de associação
        await db.commit()

        # 3) recarrega o grupo com members via selectinload,
        #    já com tudo em memória (sem lazy-load depois)
        stmt = (
            select(SupportGroup)
            .options(selectinload(SupportGroup.members))
            .where(SupportGroup.id == group_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one()

    async def update_with_members(
        self,
        db: AsyncSession,
        *,
        db_obj: SupportGroup,
        obj_in: SupportGroupUpdate,
    ) -> SupportGroup:
        data = obj_in.dict(exclude_unset=True)

        if "name" in data:
            db_obj.name = data["name"]
        if "description" in data:
            db_obj.description = data["description"]
        if "is_active" in data:
            db_obj.is_active = data["is_active"]
        if "default_sla_minutes" in data:
            db_obj.default_sla_minutes = data["default_sla_minutes"]
        if "chatwoot_inbox_identifier" in data:
            db_obj.chatwoot_inbox_identifier = data["chatwoot_inbox_identifier"]
        if "chatwoot_team_id" in data:
            db_obj.chatwoot_team_id = data["chatwoot_team_id"]

        # se vier member_ids, substitui a lista de membros
        if "member_ids" in data and data["member_ids"] is not None:
            # ✅ garante que o relacionamento já está carregado em memória
            # evita lazy-load em async (MissingGreenlet)
            await db.execute(
                select(SupportGroup)
                .options(selectinload(SupportGroup.members))
                .where(SupportGroup.id == db_obj.id)
            )

            members = await self._get_members_by_ids(db, data["member_ids"])
            db_obj.members = members

        await db.flush()
        group_id = db_obj.id
        await db.commit()

        # recarrega com membros já carregados
        stmt = (
            select(SupportGroup)
            .options(selectinload(SupportGroup.members))
            .where(SupportGroup.id == group_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one()


support_group = CRUDSupportGroup(SupportGroup)
