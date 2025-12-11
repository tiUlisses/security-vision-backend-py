# app/schemas/device_event.py
from datetime import datetime
from typing import Any, Optional, Dict

from pydantic import BaseModel, ConfigDict


class DeviceEventBase(BaseModel):
    device_id: int
    topic: str
    analytic_type: str
    payload: Optional[dict[str, Any]] = None
    occurred_at: Optional[datetime] = None


class DeviceEventCreate(DeviceEventBase):
    """
    Corpo de criação de DeviceEvent.
    - device_id será usado quando criarmos eventos sem path param.
      Na rota /devices/cameras/{camera_id}/events a gente força o device_id = camera_id.
    """
    device_id: Optional[int] = None


class DeviceEventRead(DeviceEventBase):
    id: int
    device_id: int
    created_at: datetime

    class Config:
        orm_mode = True  # se estiver em Pydantic v1
        # from_attributes = True  # se estiver em Pydantic v2
