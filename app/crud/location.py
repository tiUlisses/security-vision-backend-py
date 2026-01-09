from typing import Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.floor import Floor
from app.models.location import Location
from app.schemas.location import LocationCreate, LocationUpdate


class CRUDLocation(CRUDBase[Location, LocationCreate, LocationUpdate]):
    async def get_multi_with_floors(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Location]:
        stmt = select(Location).offset(skip).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().unique().all()

    async def set_floors(
        self,
        db: AsyncSession,
        *,
        location: Location,
        floor_ids: Iterable[int],
    ) -> Location:
        stmt = select(Floor).where(Floor.id.in_(list(floor_ids)))
        result = await db.execute(stmt)
        floors = result.scalars().all()
        location.floors = list(floors)
        db.add(location)
        await db.commit()
        await db.refresh(location)
        return location

    async def create_with_floors(
        self,
        db: AsyncSession,
        *,
        obj_in: LocationCreate,
        floors: Optional[List[Floor]] = None,
    ) -> Location:
        data = obj_in.model_dump(exclude_unset=True)
        floor_ids = data.pop("floor_ids", [])
        db_obj = Location(**data)
        if floors is None:
            floors = []
            if floor_ids:
                stmt = select(Floor).where(Floor.id.in_(floor_ids))
                result = await db.execute(stmt)
                floors = result.scalars().all()
        db_obj.floors = list(floors)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update_with_floors(
        self,
        db: AsyncSession,
        *,
        db_obj: Location,
        obj_in: LocationUpdate,
    ) -> Location:
        data = obj_in.model_dump(exclude_unset=True)
        floor_ids = data.pop("floor_ids", None)
        for field, value in data.items():
            setattr(db_obj, field, value)
        if floor_ids is not None:
            stmt = select(Floor).where(Floor.id.in_(floor_ids))
            result = await db.execute(stmt)
            db_obj.floors = list(result.scalars().all())
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj


location = CRUDLocation(Location)
