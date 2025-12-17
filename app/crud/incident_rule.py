# app/crud/incident_rule.py
from typing import List

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.incident_rule import IncidentRule
from app.models.device_event import DeviceEvent
from app.models.camera_group import CameraGroupDevice
from app.schemas.incident_rule import IncidentRuleCreate, IncidentRuleUpdate


class CRUDIncidentRule(
    CRUDBase[IncidentRule, IncidentRuleCreate, IncidentRuleUpdate]
):
    async def list_matching_event(
        self,
        db: AsyncSession,
        *,
        event: DeviceEvent,
    ) -> List[IncidentRule]:
        """
        Regras compatíveis com um DeviceEvent:
        - enabled = true
        - analytic_type igual ao do evento
        - tenant nulo OU igual ao tenant do evento
        - escopo:
          * global (device_id NULL e camera_group_id NULL)
          * device_id == event.device_id
          * camera_group_id em grupos aos quais a câmera pertence
        """
        analytic = (event.analytic_type or "").strip()

        # 1) pegar grupos aos quais a câmera pertence
        stmt_groups = select(CameraGroupDevice.camera_group_id).where(
            CameraGroupDevice.device_id == event.device_id
        )
        result_groups = await db.execute(stmt_groups)
        group_ids = [row[0] for row in result_groups.all()]

        # 2) extrair tenant do payload, se houver
        payload = event.payload or {}
        tenant = None
        if isinstance(payload, dict):
            tenant = payload.get("Tenant") or payload.get("tenant")

        # 3) montar query base
        stmt = select(IncidentRule).where(IncidentRule.enabled.is_(True))

        # analytic_type
        if analytic:
            stmt = stmt.where(IncidentRule.analytic_type == analytic)
        else:
            stmt = stmt.where(IncidentRule.analytic_type.is_(None))

        # tenant (se a regra tiver tenant definido, precisa bater)
        if tenant:
            stmt = stmt.where(
                or_(
                    IncidentRule.tenant.is_(None),
                    IncidentRule.tenant == tenant,
                )
            )

        # escopo: global OR camera OR grupo
        conditions = [
            # global: sem device e sem grupo
            and_(
                IncidentRule.device_id.is_(None),
                IncidentRule.camera_group_id.is_(None),
            ),
            # regra atrelada à câmera exata
            IncidentRule.device_id == event.device_id,
        ]

        # se a câmera pertence a algum grupo, adiciona condição por grupo
        if group_ids:
            conditions.append(IncidentRule.camera_group_id.in_(group_ids))

        stmt = stmt.where(or_(*conditions))

        result = await db.execute(stmt)
        return result.scalars().all()


incident_rule = CRUDIncidentRule(IncidentRule)
