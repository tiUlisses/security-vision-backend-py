from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CollectionLogBase(BaseModel):
    device_id: int
    tag_id: int
    rssi: Optional[int] = None
    raw_payload: Optional[str] = Field(None, max_length=4096)


class CollectionLogCreate(CollectionLogBase):
    pass


class CollectionLogUpdate(BaseModel):
    rssi: Optional[int] = None
    raw_payload: Optional[str] = Field(None, max_length=4096)


class CollectionLogRead(CollectionLogBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
