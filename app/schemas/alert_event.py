# app/schemas/alert_event.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AlertEventBase(BaseModel):
    rule_id: Optional[int] = None
    event_type: str

    person_id: Optional[int] = None
    tag_id: Optional[int] = None
    device_id: Optional[int] = None
    floor_plan_id: Optional[int] = None
    floor_id: Optional[int] = None
    building_id: Optional[int] = None
    group_id: Optional[int] = None

    # incident link
    incident_id: Optional[int] = None

    # ✅ evidências
    first_collection_log_id: Optional[int] = None
    last_collection_log_id: Optional[int] = None

    message: Optional[str] = None
    payload: Optional[str] = None


class AlertEventCreate(AlertEventBase):
    started_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    is_open: Optional[bool] = True


class AlertEventUpdate(BaseModel):
    rule_id: Optional[int] = None
    event_type: Optional[str] = None

    person_id: Optional[int] = None
    tag_id: Optional[int] = None
    device_id: Optional[int] = None
    floor_plan_id: Optional[int] = None
    floor_id: Optional[int] = None
    building_id: Optional[int] = None
    group_id: Optional[int] = None

    incident_id: Optional[int] = None

    first_collection_log_id: Optional[int] = None
    last_collection_log_id: Optional[int] = None

    started_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    is_open: Optional[bool] = None

    message: Optional[str] = None
    payload: Optional[str] = None


class AlertEventRead(AlertEventBase):
    id: int
    started_at: datetime
    last_seen_at: datetime
    ended_at: Optional[datetime] = None
    is_open: bool

    model_config = ConfigDict(from_attributes=True)
