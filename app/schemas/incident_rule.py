# app/schemas/incident_rule.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class IncidentRuleBase(BaseModel):
    name: str = Field(
        ...,
        description="Nome da regra (ex.: 'FaceRecognized - Entrada')",
    )
    analytic_type: str = Field(
        ...,
        description="Analítico observado pela regra (ex.: 'faceRecognized')",
    )
    device_id: Optional[int] = Field(
        None,
        description="Se informado, a regra só se aplica a esta câmera",
    )
    severity: Optional[str] = Field(
        "MEDIUM",
        description="Severidade padrão (LOW / MEDIUM / HIGH / CRITICAL)",
    )
    title_template: Optional[str] = Field(
        None,
        description=(
            "Template para título do incidente. "
            "Placeholders: {analytic_type}, {camera_name}, "
            "{device_id}, {device_code}, {building}, {floor}"
        ),
    )
    description_template: Optional[str] = Field(
        None,
        description="Template para descrição do incidente.",
    )
    assigned_to_user_id: Optional[int] = Field(
        None,
        description="Usuário para o qual o incidente será atribuído automaticamente",
    )
    is_enabled: bool = Field(
        True,
        description="Se falso, a regra é ignorada.",
    )


class IncidentRuleCreate(IncidentRuleBase):
    pass


class IncidentRuleUpdate(BaseModel):
    name: Optional[str] = None
    analytic_type: Optional[str] = None
    device_id: Optional[int | None] = None
    severity: Optional[str] = None
    title_template: Optional[str | None] = None
    description_template: Optional[str | None] = None
    assigned_to_user_id: Optional[int | None] = None
    is_enabled: Optional[bool] = None


class IncidentRuleRead(IncidentRuleBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
