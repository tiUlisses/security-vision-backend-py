#securityvision-position/app/schemas/person.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PersonBase(BaseModel):
    full_name: str = Field(..., max_length=255)
    document_id: Optional[str] = Field(None, max_length=64)
    email: Optional[str] = Field(None, max_length=255)
    active: bool = True
    notes: Optional[str] = Field(None, max_length=1024)


class PersonCreate(PersonBase):
    pass


class PersonUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=255)
    document_id: Optional[str] = Field(None, max_length=64)
    email: Optional[str] = Field(None, max_length=255)
    active: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=1024)


class PersonRead(PersonBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
