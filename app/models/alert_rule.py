#securityvision-position/app/models/alert_rule.py
from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.person_group import PersonGroup
    from app.models.device import Device
    from app.models.alert_event import AlertEvent


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # FORBIDDEN_SECTOR, DWELL_TIME, etc.
    rule_type: Mapped[str] = mapped_column(String(64), nullable=False)

    group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("person_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    device_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # usado em regras de tempo de permanência (MVP: só modelado)
    max_dwell_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("TRUE"),
    )

    created_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    group: Mapped[Optional["PersonGroup"]] = relationship(
        back_populates="alert_rules",
    )
    device: Mapped[Optional["Device"]] = relationship(
        back_populates="alert_rules",
    )
    events: Mapped[list["AlertEvent"]] = relationship(
        back_populates="rule",
        cascade="all, delete-orphan",
    )
