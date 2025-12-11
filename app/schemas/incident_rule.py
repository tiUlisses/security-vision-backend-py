# app/schemas/incident_rule.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class IncidentRuleBase(BaseModel):
    name: str
    enabled: bool = True

    analytic_type: Optional[str] = None
    device_id: Optional[int] = None
    tenant: Optional[str] = None

    severity: str = "MEDIUM"  # LOW / MEDIUM / HIGH / CRITICAL

    title_template: Optional[str] = None
    description_template: Optional[str] = None

    assigned_to_user_id: Optional[int] = None


class IncidentRuleCreate(IncidentRuleBase):
    """
    Por enquanto não exigimos nenhum campo extra além do base.
    """
    pass


class IncidentRuleUpdate(BaseModel):
    """
    Atualização parcial (PATCH).
    Todos os campos opcionais.
    """
    name: Optional[str] = None
    enabled: Optional[bool] = None

    analytic_type: Optional[str] = None
    device_id: Optional[int] = None
    tenant: Optional[str] = None

    severity: Optional[str] = None

    title_template: Optional[str] = None
    description_template: Optional[str] = None

    assigned_to_user_id: Optional[int] = None


class IncidentRuleRead(IncidentRuleBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
