# app/schemas/device_user.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DeviceUserBase(BaseModel):
    device_id: int
    person_id: int
    device_user_id: str = Field(..., max_length=128)
    status: str = Field(..., max_length=32)


class DeviceUserCreate(DeviceUserBase):
    pass


class DeviceUserUpdate(BaseModel):
    device_id: Optional[int] = None
    person_id: Optional[int] = None
    device_user_id: Optional[str] = Field(None, max_length=128)
    status: Optional[str] = Field(None, max_length=32)


class DeviceUserRead(DeviceUserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
