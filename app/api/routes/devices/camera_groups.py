# app/api/routes/devices/camera_groups.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_active_user
from app.models.user import User
from app.crud.camera_group import camera_group as crud_camera_group
from app.schemas import (
    CameraGroupCreate,
    CameraGroupRead,
    CameraGroupUpdate,
)

router = APIRouter()


@router.get("/", response_model=List[CameraGroupRead])
async def list_camera_groups(
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    groups = await crud_camera_group.get_multi(db)
    # Monta device_ids manualmente pra bater com o schema
    return [
        CameraGroupRead(
            id=g.id,
            name=g.name,
            description=g.description,
            tenant=g.tenant,
            created_at=g.created_at,
            updated_at=g.updated_at,
            device_ids=[d.id for d in (g.devices or [])],
        )
        for g in groups
    ]


@router.post(
    "/",
    response_model=CameraGroupRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_camera_group(
    group_in: CameraGroupCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    group = await crud_camera_group.create_with_devices(db, obj_in=group_in)
    return CameraGroupRead(
        id=group.id,
        name=group.name,
        description=group.description,
        tenant=group.tenant,
        created_at=group.created_at,
        updated_at=group.updated_at,
        device_ids=[d.id for d in (group.devices or [])],
    )


@router.get(
    "/{group_id}",
    response_model=CameraGroupRead,
)
async def get_camera_group(
    group_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    group = await crud_camera_group.get(db, id=group_id)
    if not group:
        raise HTTPException(status_code=404, detail="CameraGroup not found")

    return CameraGroupRead(
        id=group.id,
        name=group.name,
        description=group.description,
        tenant=group.tenant,
        created_at=group.created_at,
        updated_at=group.updated_at,
        device_ids=[d.id for d in (group.devices or [])],
    )


@router.patch(
    "/{group_id}",
    response_model=CameraGroupRead,
)
async def update_camera_group(
    group_id: int,
    group_in: CameraGroupUpdate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    db_group = await crud_camera_group.get(db, id=group_id)
    if not db_group:
        raise HTTPException(status_code=404, detail="CameraGroup not found")

    group = await crud_camera_group.update_with_devices(
        db, db_obj=db_group, obj_in=group_in
    )
    return CameraGroupRead(
        id=group.id,
        name=group.name,
        description=group.description,
        tenant=group.tenant,
        created_at=group.created_at,
        updated_at=group.updated_at,
        device_ids=[d.id for d in (group.devices or [])],
    )


@router.delete(
    "/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_camera_group(
    group_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    db_group = await crud_camera_group.get(db, id=group_id)
    if not db_group:
        raise HTTPException(status_code=404, detail="CameraGroup not found")

    await crud_camera_group.remove(db, id=group_id)
    return None
