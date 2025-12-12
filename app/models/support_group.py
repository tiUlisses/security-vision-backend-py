# app/models/support_group.py
from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    String,
    Text,
    Boolean,
    Integer,
    ForeignKey,
    Table,
    Column,  # <- IMPORTANTE: usar Column aqui
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.incident import Incident


# 🔹 TABELA DE ASSOCIAÇÃO: NÃO usar mapped_column aqui
support_group_members = Table(
    "support_group_members",
    Base.metadata,
    Column(
        "group_id",
        ForeignKey("support_groups.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "user_id",
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class SupportGroup(Base):
    __tablename__ = "support_groups"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ponte com Chatwoot
    chatwoot_inbox_identifier: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    chatwoot_team_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    default_sla_minutes: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )

    members: Mapped[List["User"]] = relationship(
        "User",
        secondary=support_group_members,
        back_populates="support_groups",
    )

    incidents: Mapped[List["Incident"]] = relationship(
        "Incident",
        back_populates="assigned_group",
    )
