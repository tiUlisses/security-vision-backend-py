# app/schemas/support_group.py

from typing import Optional, List
from pydantic import BaseModel

from app.schemas.user import UserShort


class SupportGroupBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True
    default_sla_minutes: Optional[int] = None
    chatwoot_inbox_identifier: Optional[str] = None
    chatwoot_team_id: Optional[int] = None


class SupportGroupCreate(SupportGroupBase):
    member_ids: List[int] = []


class SupportGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    default_sla_minutes: Optional[int] = None
    chatwoot_inbox_identifier: Optional[str] = None
    chatwoot_team_id: Optional[int] = None
    member_ids: Optional[List[int]] = None


class SupportGroupRead(SupportGroupBase):
    id: int
    members: List[UserShort] = []

    class Config:
        from_attributes = True
