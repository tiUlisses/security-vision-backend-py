from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BuildingBase(BaseModel):
    name: str = Field(..., max_length=255)
    code: str = Field(..., max_length=64)
    description: Optional[str] = Field(None, max_length=1024)


class BuildingCreate(BuildingBase):
    pass


class BuildingUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    code: Optional[str] = Field(None, max_length=64)
    description: Optional[str] = Field(None, max_length=1024)


class BuildingRead(BuildingBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
