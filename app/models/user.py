# app/models/user.py
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List
from app.models.incident_assignee import incident_assignees
from sqlalchemy import Boolean, DateTime, String, text, Column, Text, Table, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.support_group import support_group_members
from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.incident import Incident
    from app.models.incident_message import IncidentMessage
    from app.models.support_group import SupportGroup


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    # 🔹 AQUI é o campo que estava faltando
    role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'OPERATOR'"),
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("TRUE"),
    )

    is_superuser: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
    )
    chatwoot_agent_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
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
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    assigned_incidents: Mapped[List["Incident"]] = relationship(
        "Incident",
        secondary=incident_assignees,
        back_populates="assignees",
    )
    
    incidents_assigned: Mapped[List["Incident"]] = relationship(
        "Incident",
        back_populates="assigned_to",
        foreign_keys="Incident.assigned_to_user_id",
    )

    support_groups: Mapped[List["SupportGroup"]] = relationship(
        "SupportGroup",
        secondary=support_group_members,
        back_populates="members",
    )

    assigned_incidents: Mapped[List["Incident"]] = relationship(
        "Incident",
        secondary=incident_assignees,
        back_populates="assignees",
    )

    incidents_created: Mapped[List["Incident"]] = relationship(
        "Incident",
        back_populates="created_by",
        foreign_keys="Incident.created_by_user_id",
    )