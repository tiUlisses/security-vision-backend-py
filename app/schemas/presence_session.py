# app/schemas/presence_session.py
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PresenceSessionRead(BaseModel):
    id: int
    device_id: int
    tag_id: int
    started_at: datetime
    ended_at: datetime
    duration_seconds: int
    samples_count: int

    model_config = ConfigDict(from_attributes=True)
