# securityvision-position/app/schemas/floor_plan.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class FloorPlanBase(BaseModel):
    floor_id: int
    name: str = Field(..., max_length=255)
    image_url: Optional[str] = Field(None, max_length=1024)
    width: Optional[float] = None
    height: Optional[float] = None
    description: Optional[str] = Field(None, max_length=1024)


class FloorPlanCreate(FloorPlanBase):
    pass


class FloorPlanUpdate(BaseModel):
    floor_id: Optional[int] = None
    name: Optional[str] = Field(None, max_length=255)
    image_url: Optional[str] = Field(None, max_length=1024)
    width: Optional[float] = None
    height: Optional[float] = None
    description: Optional[str] = Field(None, max_length=1024)


class FloorPlanRead(FloorPlanBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
