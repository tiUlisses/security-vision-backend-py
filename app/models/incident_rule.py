# app/models/incident_rule.py
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.device import Device
    from app.models.user import User


class IncidentRule(Base):
    __tablename__ = "incident_rules"
    __allow_unmapped__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Nome da regra (ex.: "FaceRecognized - Entrada")
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Analítico que dispara a regra (ex.: "faceRecognized", "FaceDetection")
    analytic_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )

    # Se preenchido, a regra vale apenas para essa câmera específica.
    # Se for NULL, vale para qualquer câmera que gere esse analítico.
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Severidade padrão dos incidentes criados por esta regra
    severity: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="MEDIUM",
    )

    # Templates de título/descrição do incidente criado
    # placeholders suportados: {analytic_type}, {camera_name}, {device_id},
    # {device_code}, {building}, {floor}
    title_template: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    description_template: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Operador para o qual o incidente será atribuído automaticamente (opcional)
    assigned_to_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Se false, a regra é ignorada
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        default=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    # Relações
    device: Mapped["Device"] | None = relationship("Device")
    assigned_to_user: Mapped["User"] | None = relationship("User")
