#securityvision-position/app/api/routes/floors.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.crud import floor as crud_floor
from app.schemas import FloorCreate, FloorRead, FloorUpdate

router = APIRouter()


@router.get("/", response_model=List[FloorRead])
async def list_floors(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db_session),
):
    return await crud_floor.get_multi(db, skip=skip, limit=limit)


@router.post(
    "/",
    response_model=FloorRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_floor(
    floor_in: FloorCreate,
    db: AsyncSession = Depends(get_db_session),
):
    return await crud_floor.create(db, floor_in)


@router.get("/{floor_id}", response_model=FloorRead)
async def get_floor(
    floor_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_floor.get(db, id=floor_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Floor not found")
    return db_obj


@router.put("/{floor_id}", response_model=FloorRead)
async def update_floor(
    floor_id: int,
    floor_in: FloorUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_floor.get(db, id=floor_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Floor not found")
    return await crud_floor.update(db, db_obj, floor_in)


@router.delete("/{floor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_floor(
    floor_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    deleted = await crud_floor.remove(db, id=floor_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Floor not found")
    return None
