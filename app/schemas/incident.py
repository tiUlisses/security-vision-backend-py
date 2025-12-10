# app/schemas/incident.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


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
    pass


class IncidentUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    severity: Optional[str] = Field(None, max_length=32)
    status: Optional[str] = Field(None, max_length=32)

    # 🔹 permitir atualizar SLA e due_at se quiser
    sla_minutes: Optional[int] = None
    due_at: Optional[datetime] = None

    # se quiser, também permitir editar tenant/kind
    tenant: Optional[str] = Field(None, max_length=64)
    kind: Optional[str] = Field(None, max_length=64)


class IncidentRead(IncidentBase):
    id: int
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None

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
