#securityvision-position/app/schemas/alert_rule.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AlertRuleBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = Field(None, max_length=1024)
    rule_type: str = Field(..., max_length=64)  # ex: FORBIDDEN_SECTOR
    group_id: Optional[int] = None
    device_id: Optional[int] = None
    max_dwell_seconds: Optional[int] = None
    is_active: bool = True


class AlertRuleCreate(AlertRuleBase):
    pass


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=1024)
    rule_type: Optional[str] = Field(None, max_length=64)
    group_id: Optional[int] = None
    device_id: Optional[int] = None
    max_dwell_seconds: Optional[int] = None
    is_active: Optional[bool] = None


class AlertRuleRead(AlertRuleBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
