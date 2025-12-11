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
        analytic = (event.analytic_type or "").strip()

        print(
            f"[incident-rules] procurando regras para "
            f"analytic='{analytic}', device_id={event.device_id}"
        )

        stmt = select(IncidentRule).where(IncidentRule.enabled.is_(True))

        if analytic:
            stmt = stmt.where(IncidentRule.analytic_type == analytic)
        else:
            stmt = stmt.where(IncidentRule.analytic_type.is_(None))

        stmt = stmt.where(
            or_(
                IncidentRule.device_id.is_(None),
                IncidentRule.device_id == event.device_id,
            )
        )

        result = await db.execute(stmt)
        rules = result.scalars().all()

        print(
            f"[incident-rules] encontradas {len(rules)} regras compatíveis "
            f"para analytic='{analytic}', device_id={event.device_id}"
        )

        return rules


incident_rule = CRUDIncidentRule(IncidentRule)
