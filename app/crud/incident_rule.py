# app/crud/incident_rule.py
from typing import List

from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.incident_rule import IncidentRule
from app.models.device_event import DeviceEvent
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
        Retorna regras ativas que se aplicam a este DeviceEvent.

        Critérios (v1):
        - is_enabled = true
        - analytic_type (case-insensitive) == event.analytic_type
        - (device_id IS NULL) OU (device_id == event.device_id)
        """

        analytic = (event.analytic_type or "").lower()

        stmt = (
            select(IncidentRule)
            .where(IncidentRule.is_enabled.is_(True))
            .where(func.lower(IncidentRule.analytic_type) == analytic)
            .where(
                or_(
                    IncidentRule.device_id.is_(None),
                    IncidentRule.device_id == event.device_id,
                )
            )
        )

        result = await db.execute(stmt)
        return result.scalars().all()


incident_rule = CRUDIncidentRule(IncidentRule)
