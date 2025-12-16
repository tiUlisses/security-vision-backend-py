# app/models/alert_event.py
from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.alert_rule import AlertRule
    from app.models.person import Person
    from app.models.tag import Tag
    from app.models.device import Device
    from app.models.floor_plan import FloorPlan
    from app.models.floor import Floor
    from app.models.building import Building
    from app.models.person_group import PersonGroup


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    rule_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)

    person_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("people.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tag_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tags.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    device_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    floor_plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("floor_plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    floor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("floors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    building_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("buildings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("person_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Já adicionamos antes (incidente opcional)
    incident_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ✅ NOVO: evidência (CollectionLog que abriu e que atualizou por último)
    first_collection_log_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("collection_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_collection_log_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("collection_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_open: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("TRUE"),
        default=True,
    )

    message: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    rule: Mapped[Optional["AlertRule"]] = relationship(back_populates="events")
    person: Mapped[Optional["Person"]] = relationship()
    tag: Mapped[Optional["Tag"]] = relationship()
    device: Mapped[Optional["Device"]] = relationship()
    floor_plan: Mapped[Optional["FloorPlan"]] = relationship()
    floor: Mapped[Optional["Floor"]] = relationship()
    building: Mapped[Optional["Building"]] = relationship()
    group: Mapped[Optional["PersonGroup"]] = relationship()
