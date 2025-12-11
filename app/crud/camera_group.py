# app/crud/camera_group.py
from typing import Any, Dict, List, Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.camera_group import CameraGroup, CameraGroupDevice
from app.schemas.camera_group import CameraGroupCreate, CameraGroupUpdate


class CRUDCameraGroup(
    CRUDBase[CameraGroup, CameraGroupCreate, CameraGroupUpdate]
):
    async def create_with_devices(
        self,
        db: AsyncSession,
        *,
        obj_in: CameraGroupCreate,
    ) -> CameraGroup:
        data = obj_in.model_dump(exclude={"device_ids"})
        device_ids = obj_in.device_ids or []

        group = CameraGroup(**data)
        db.add(group)
        await db.flush()  # garante group.id

        for dev_id in device_ids:
            db.add(
                CameraGroupDevice(
                    camera_group_id=group.id,
                    device_id=dev_id,
                )
            )

        await db.commit()
        await db.refresh(group)
        return group

    async def update_with_devices(
        self,
        db: AsyncSession,
        *,
        db_obj: CameraGroup,
        obj_in: CameraGroupUpdate,
    ) -> CameraGroup:
        data = obj_in.model_dump(exclude_unset=True)
        device_ids = data.pop("device_ids", None)

        # Atualiza campos simples
        for field, value in data.items():
            setattr(db_obj, field, value)

        # Atualiza relação many-to-many só se veio device_ids no payload
        if device_ids is not None:
            await db.execute(
                delete(CameraGroupDevice).where(
                    CameraGroupDevice.camera_group_id == db_obj.id
                )
            )
            for dev_id in device_ids:
                db.add(
                    CameraGroupDevice(
                        camera_group_id=db_obj.id,
                        device_id=dev_id,
                    )
                )

        await db.commit()
        await db.refresh(db_obj)
        return db_obj


camera_group = CRUDCameraGroup(CameraGroup)
