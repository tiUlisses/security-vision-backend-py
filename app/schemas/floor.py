from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class FloorBase(BaseModel):
    building_id: int
    name: str = Field(..., max_length=255)
    level: Optional[int] = None
    description: Optional[str] = Field(None, max_length=1024)


class FloorCreate(FloorBase):
    pass


class FloorUpdate(BaseModel):
    building_id: Optional[int] = None
    name: Optional[str] = Field(None, max_length=255)
    level: Optional[int] = None
    description: Optional[str] = Field(None, max_length=1024)


class FloorRead(FloorBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
