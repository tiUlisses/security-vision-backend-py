# app/crud/building.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.building import Building
from app.schemas.building import BuildingCreate, BuildingUpdate


class CRUDBuilding(CRUDBase[Building, BuildingCreate, BuildingUpdate]):
    async def get_by_code(self, db: AsyncSession, code: str) -> Building | None:
        stmt = select(self.model).where(self.model.code == code)
        result = await db.execute(stmt)
        return result.scalars().first()


building = CRUDBuilding(Building)