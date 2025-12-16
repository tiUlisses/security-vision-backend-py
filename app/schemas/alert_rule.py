# securityvision-position/app/schemas/alert_rule.py
from __future__ import annotations

from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field, ConfigDict

IncidentSeverity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class AlertRuleBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = Field(None, max_length=1024)
    rule_type: str = Field(..., max_length=64)  # ex: FORBIDDEN_SECTOR, DWELL_TIME
    group_id: Optional[int] = None
    device_id: Optional[int] = None
    max_dwell_seconds: Optional[int] = Field(default=None, ge=0)
    is_active: bool = True

    # ---------------------------------------------------------
    # Integração opcional com INCIDENTES (RTLS)
    # ---------------------------------------------------------
    create_incident: bool = False
    incident_kind: Optional[str] = Field(default=None, max_length=64)
    incident_severity: IncidentSeverity = "MEDIUM"

    incident_title_template: Optional[str] = Field(default=None, max_length=255)
    incident_description_template: Optional[str] = None

    incident_sla_minutes: Optional[int] = Field(default=None, ge=0)

    incident_assigned_group_id: Optional[int] = None
    incident_assigned_to_user_id: Optional[int] = None

    incident_auto_close_on_end: bool = False


class AlertRuleCreate(AlertRuleBase):
    pass


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=1024)
    rule_type: Optional[str] = Field(None, max_length=64)
    group_id: Optional[int] = None
    device_id: Optional[int] = None
    max_dwell_seconds: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None

    # incident config (tudo opcional no update)
    create_incident: Optional[bool] = None
    incident_kind: Optional[str] = Field(default=None, max_length=64)
    incident_severity: Optional[IncidentSeverity] = None
    incident_title_template: Optional[str] = Field(default=None, max_length=255)
    incident_description_template: Optional[str] = None
    incident_sla_minutes: Optional[int] = Field(default=None, ge=0)
    incident_assigned_group_id: Optional[int] = None
    incident_assigned_to_user_id: Optional[int] = None
    incident_auto_close_on_end: Optional[bool] = None


class AlertRuleRead(AlertRuleBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
