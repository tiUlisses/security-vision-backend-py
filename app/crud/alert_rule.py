# app/crud/alert_rule.py
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.alert_rule import AlertRule
from app.schemas.alert_rule import AlertRuleCreate, AlertRuleUpdate


class CRUDAlertRule(CRUDBase[AlertRule, AlertRuleCreate, AlertRuleUpdate]):
    async def get_multi_for_device(
        self,
        db: AsyncSession,
        device_id: int,
    ) -> List[AlertRule]:
        """
        Retorna todas as regras ATIVAS associadas a um device específico.
        """
        stmt = (
            select(AlertRule)
            .where(
                AlertRule.device_id == device_id,
                AlertRule.is_active == True,  # noqa: E712
            )
            .order_by(AlertRule.id.asc())
        )
        result = await db.execute(stmt)
        return result.scalars().all()


# 👇 ESTA é a instância que queremos usar no alert_engine
alert_rule = CRUDAlertRule(AlertRule)
