# app/api/routes/device_users.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.crud import device_user as crud_device_user
from app.schemas.device_user import (
    DeviceUserCreate,
    DeviceUserRead,
    DeviceUserUpdate,
)
from app.services.access_control_publisher import (
    publish_access_control_device_user_created,
    publish_access_control_device_user_deleted,
    publish_access_control_device_user_updated,
)

router = APIRouter()


@router.get("/", response_model=List[DeviceUserRead])
async def list_device_users(
    skip: int = 0,
    limit: int = 100,
    device_id: int | None = Query(default=None),
    person_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    device_users = await crud_device_user.get_multi(db, skip=skip, limit=limit)
    if device_id is not None:
        device_users = [item for item in device_users if item.device_id == device_id]
    if person_id is not None:
        device_users = [item for item in device_users if item.person_id == person_id]
    return device_users


@router.post(
    "/",
    response_model=DeviceUserRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_device_user(
    device_user_in: DeviceUserCreate,
    db: AsyncSession = Depends(get_db_session),
):
    device_user = await crud_device_user.create(db, device_user_in)
    await publish_access_control_device_user_created(device_user)
    return device_user


@router.get("/{device_user_id}", response_model=DeviceUserRead)
async def get_device_user(
    device_user_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_device_user.get(db, id=device_user_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Device user not found")
    return db_obj


@router.put("/{device_user_id}", response_model=DeviceUserRead)
async def update_device_user(
    device_user_id: int,
    device_user_in: DeviceUserUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_device_user.get(db, id=device_user_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Device user not found")
    updated = await crud_device_user.update(db, db_obj, device_user_in)
    await publish_access_control_device_user_updated(updated)
    return updated


@router.delete("/{device_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device_user(
    device_user_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    deleted = await crud_device_user.remove(db, id=device_user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Device user not found")
    await publish_access_control_device_user_deleted()
    return None
