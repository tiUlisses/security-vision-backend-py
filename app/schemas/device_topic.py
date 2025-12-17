# app/schemas/device_topic.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DeviceTopicBase(BaseModel):
    device_id: int
    kind: str = Field(..., max_length=32)
    topic: str = Field(..., max_length=512)
    description: Optional[str] = Field(None, max_length=512)


class DeviceTopicCreate(DeviceTopicBase):
    pass


class DeviceTopicUpdate(BaseModel):
    description: Optional[str] = Field(None, max_length=512)
    is_active: Optional[bool] = None


class DeviceTopicRead(DeviceTopicBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
