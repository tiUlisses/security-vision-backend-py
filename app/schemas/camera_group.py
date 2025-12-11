# app/schemas/camera_group.py
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class CameraGroupBase(BaseModel):
    name: str
    description: Optional[str] = None
    tenant: Optional[str] = None


class CameraGroupCreate(CameraGroupBase):
    # lista de IDs de devices (câmeras) que pertencem ao grupo
    device_ids: List[int] = []


class CameraGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tenant: Optional[str] = None
    device_ids: Optional[List[int]] = None


class CameraGroupRead(CameraGroupBase):
    id: int
    device_ids: List[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
