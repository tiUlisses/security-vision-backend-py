# app/models/incident.py
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional, List

from sqlalchemy import DateTime, ForeignKey, String, Text, text, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.support_group import SupportGroup
from app.models.incident_assignee import incident_assignees
from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.device import Device
    from app.models.device_event import DeviceEvent
    from app.models.incident_message import IncidentMessage
    from app.models.user import User


class Incident(Base):
    __tablename__ = "incidents"
    __allow_unmapped__ = True

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    device_event_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("device_events.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )

    # Ex.: CAMERA_OFFLINE, CAMERA_FACE, CAMERA_INTRUSION, etc.
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # 🔹 NOVO: tenant (ex.: "howbe")
    tenant: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    # Status do fluxo de atendimento
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    # LOW / MEDIUM / HIGH / CRITICAL
    severity: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # 🔹 NOVO: SLA em minutos e due_at calculado
    sla_minutes: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )

    due_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    chatwoot_conversation_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
        index=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    device: Mapped["Device"] = relationship(
        "Device",
        back_populates="incidents",
    )

    device_event: Mapped[Optional["DeviceEvent"]] = relationship(
        "DeviceEvent",
        back_populates="incident",
        uselist=False,
    )

    messages: Mapped[List["IncidentMessage"]] = relationship(
        "IncidentMessage",
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="IncidentMessage.created_at",
    )

    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Usuário atualmente responsável / atribuído ao incidente
    assigned_to_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Usuário que criou o incidente
    created_by: Mapped["User"] = relationship(
        "User",
        back_populates="incidents_created",
        foreign_keys="Incident.created_by_user_id",
    )

    # Usuário atualmente atribuído
    assigned_to: Mapped["User"] = relationship(
        "User",
        back_populates="incidents_assigned",
        foreign_keys="Incident.assigned_to_user_id",
    )

    attachments: Mapped[List["IncidentAttachment"]] = relationship(
        "IncidentAttachment",
        back_populates="incident",
        cascade="all, delete-orphan",
    )

    device: Mapped["Device"] = relationship("Device")
    device_event: Mapped["DeviceEvent"] | None = relationship("DeviceEvent")

    assigned_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("support_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    assigned_group: Mapped["SupportGroup"] = relationship(
        "SupportGroup",
        back_populates="incidents",
    )

    # 🔹 NOVO: lista de pessoas atuando no incidente
    assignees: Mapped[List["User"]] = relationship(
        "User",
        secondary=incident_assignees,
        back_populates="assigned_incidents",
    )