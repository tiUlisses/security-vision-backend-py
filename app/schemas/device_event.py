# app/schemas/device_event.py
from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, Field


class DeviceEventRead(BaseModel):
    id: int
    device_id: int
    topic: str = Field(..., max_length=512)
    analytic_type: str = Field(..., max_length=64)
    payload: Dict[str, Any]
    occurred_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True
