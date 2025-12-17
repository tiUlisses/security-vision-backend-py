# app/crud/floor_plan.py

from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.floor_plan import FloorPlan
from app.schemas.floor_plan import FloorPlanCreate, FloorPlanUpdate


class CRUDFloorPlan(CRUDBase[FloorPlan, FloorPlanCreate, FloorPlanUpdate]):
    async def get_multi_by_building(
        self,
        db: AsyncSession,
        building_id: int,
    ) -> List[FloorPlan]:
        """
        Retorna todas as plantas (FloorPlan) cujos andares (Floor)
        pertencem ao prédio informado (building_id).
        """
        stmt = (
            select(self.model)
            .where(self.model.floor.has(building_id=building_id))  # 👈 usa o relacionamento
            .order_by(self.model.name)
        )

        result = await db.execute(stmt)
        return result.scalars().all()


floor_plan = CRUDFloorPlan(FloorPlan)
