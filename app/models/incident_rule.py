# app/models/incident_rule.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
    Column
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class IncidentRule(Base):
    __tablename__ = "incident_rules"
    __allow_unmapped__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Nome amigável da regra
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Ativa / inativa
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        index=True,
    )

    # Filtro principal: tipo de analítico (FaceRecognized, FaceDetection, Intrusion, etc.)
    # Se for NULL, significaria "qualquer analítico" (podemos suportar isso depois).
    analytic_type: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

    # Escopo da regra: específica de uma câmera (device) ou genérica (NULL = qualquer câmera)
    device_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Tenant opcional
    tenant: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    # Severidade padrão para incidentes criados por esta regra
    severity: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="MEDIUM",
    )

    # Templates de título/descrição (usados com .format(**ctx) no service)
    title_template: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    description_template: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # Usuário para o qual o incidente será atribuído automaticamente (opcional)
    assigned_to_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
    camera_group_id = Column(
        Integer,
        ForeignKey("camera_groups.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relações
    device = relationship("Device")
    camera_group = relationship("CameraGroup", lazy="selectin")
    assigned_to = relationship(
        "User",
        foreign_keys=[assigned_to_user_id],
    )
