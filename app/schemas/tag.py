#securityvision-position/app/schemas/tag.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TagBase(BaseModel):
    mac_address: str = Field(..., max_length=64)
    label: Optional[str] = Field(None, max_length=255)
    person_id: Optional[int] = None
    active: bool = True
    notes: Optional[str] = Field(None, max_length=1024)


class TagCreate(TagBase):
    pass


class TagUpdate(BaseModel):
    mac_address: Optional[str] = Field(None, max_length=64)
    label: Optional[str] = Field(None, max_length=255)
    person_id: Optional[int] = None
    active: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=1024)


class TagRead(TagBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
