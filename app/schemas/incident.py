# app/schemas/incident.py
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field
from app.schemas.user import UserShort  # ou o nome que você tiver
from app.schemas.support_group import SupportGroupRead  # vamos criar já já

class IncidentBase(BaseModel):
    device_id: int
    device_event_id: Optional[int] = None

    kind: str = Field("CAMERA_EVENT", max_length=64)

    # 🔹 NOVO
    tenant: Optional[str] = Field(None, max_length=64)

    status: str = Field("OPEN", max_length=32)
    severity: str = Field("MEDIUM", max_length=32)

    title: str = Field(..., max_length=255)
    description: Optional[str] = None

    # 🔹 NOVO: SLA e due_at
    sla_minutes: Optional[int] = None
    due_at: Optional[datetime] = None


class IncidentCreate(IncidentBase):
    # opcional: já criar com responsável / grupo / time
    assigned_to_user_id: Optional[int] = None
    assigned_group_id: Optional[int] = None
    assignee_ids: Optional[List[int]] = None
    # (você pode começar só com assigned_group_id se quiser)

class IncidentUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    severity: Optional[str] = Field(None, max_length=32)
    status: Optional[str] = Field(None, max_length=32)
    chatwoot_conversation_id: Optional[int] = None   # 🔹 novo
    sla_minutes: Optional[int] = None
    due_at: Optional[datetime] = None

    tenant: Optional[str] = Field(None, max_length=64)
    kind: Optional[str] = Field(None, max_length=64)

    # 🔹 NOVO: edição de atribuição
    assigned_to_user_id: Optional[int] = None
    assigned_group_id: Optional[int] = None
    assignee_ids: Optional[List[int]] = None


class IncidentRead(IncidentBase):
    id: int
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None
    assigned_group: Optional[SupportGroupRead] = None
    assignees: List[UserShort] = []
    chatwoot_conversation_id: Optional[int] = None   # 🔹 novo

    class Config:
        from_attributes = True


class IncidentFromDeviceEventCreate(BaseModel):
    device_event_id: int
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    severity: Optional[str] = Field(None, max_length=32)

    # 🔹 opcionalmente permitir override de SLA/tenant na criação por evento
    sla_minutes: Optional[int] = None
    tenant: Optional[str] = Field(None, max_length=64)
