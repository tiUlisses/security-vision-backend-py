# app/api/routes/locations.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.crud.location import location as crud_location
from app.crud.location_rule import location_rule as crud_location_rule
from app.models.floor import Floor
from app.models.location import Location, LocationRule
from app.schemas.location import (
    LocationCreate,
    LocationRead,
    LocationRuleCreate,
    LocationRuleRead,
    LocationRuleUpdate,
    LocationUpdate,
)
from app.services.access_control_projection import publish_projection_for_location
from app.services.access_control_publisher import (
    publish_access_control_location_created,
    publish_access_control_location_deleted,
    publish_access_control_location_rule_created,
    publish_access_control_location_rule_deleted,
    publish_access_control_location_rule_updated,
    publish_access_control_location_updated,
)

router = APIRouter()


def _to_location_read(location: Location) -> LocationRead:
    return LocationRead(
        id=location.id,
        name=location.name,
        description=location.description,
        status=location.status,
        floor_ids=[floor.id for floor in location.floors],
        created_at=location.created_at,
        updated_at=location.updated_at,
    )


async def _load_floors(db: AsyncSession, floor_ids: List[int]) -> List[Floor]:
    if not floor_ids:
        return []
    stmt = select(Floor).where(Floor.id.in_(floor_ids))
    result = await db.execute(stmt)
    floors = result.scalars().all()
    if len(floors) != len(set(floor_ids)):
        raise HTTPException(status_code=404, detail="One or more floors not found")
    return floors


@router.get("/", response_model=List[LocationRead])
async def list_locations(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db_session),
):
    locations = await crud_location.get_multi_with_floors(db, skip=skip, limit=limit)
    return [_to_location_read(loc) for loc in locations]


@router.post("/", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
async def create_location(
    location_in: LocationCreate,
    db: AsyncSession = Depends(get_db_session),
):
    floors = await _load_floors(db, location_in.floor_ids)
    location = await crud_location.create_with_floors(db, obj_in=location_in, floors=floors)
    await publish_projection_for_location(db, location)
    await publish_access_control_location_created(location)
    return _to_location_read(location)


@router.get("/{location_id}", response_model=LocationRead)
async def get_location(
    location_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    location = await crud_location.get(db, id=location_id)
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")
    await db.refresh(location, attribute_names=["floors"])
    return _to_location_read(location)


@router.put("/{location_id}", response_model=LocationRead)
async def update_location(
    location_id: int,
    location_in: LocationUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    location = await crud_location.get(db, id=location_id)
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")
    if location_in.floor_ids is not None:
        await _load_floors(db, location_in.floor_ids)
    updated = await crud_location.update_with_floors(db, db_obj=location, obj_in=location_in)
    await publish_projection_for_location(db, updated)
    await publish_access_control_location_updated(updated)
    return _to_location_read(updated)


@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_location(
    location_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    deleted = await crud_location.remove(db, id=location_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Location not found")
    await publish_access_control_location_deleted()
    return None


@router.get("/{location_id}/rules", response_model=List[LocationRuleRead])
async def list_location_rules(
    location_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    stmt = select(LocationRule).where(LocationRule.location_id == location_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/{location_id}/rules", response_model=LocationRuleRead, status_code=status.HTTP_201_CREATED)
async def create_location_rule(
    location_id: int,
    rule_in: LocationRuleCreate,
    db: AsyncSession = Depends(get_db_session),
):
    if rule_in.location_id != location_id:
        raise HTTPException(status_code=400, detail="location_id mismatch")
    location = await crud_location.get(db, id=location_id)
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")
    created = await crud_location_rule.create(db, obj_in=rule_in)
    await publish_access_control_location_rule_created(created)
    return created


@router.put("/rules/{rule_id}", response_model=LocationRuleRead)
async def update_location_rule(
    rule_id: int,
    rule_in: LocationRuleUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    rule = await crud_location_rule.get(db, id=rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Location rule not found")
    updated = await crud_location_rule.update(db, db_obj=rule, obj_in=rule_in)
    await publish_access_control_location_rule_updated(updated)
    return updated


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_location_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    deleted = await crud_location_rule.remove(db, id=rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Location rule not found")
    await publish_access_control_location_rule_deleted()
    return None
