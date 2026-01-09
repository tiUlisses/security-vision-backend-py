from __future__ import annotations

from datetime import datetime, time
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Column, ForeignKey, String, Table, Time, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.floor import Floor


location_floors = Table(
    "location_floors",
    Base.metadata,
    Column("location_id", ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True),
    Column("floor_id", ForeignKey("floors.id", ondelete="CASCADE"), primary_key=True),
)


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'ACTIVE'"))

    created_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    floors: Mapped[List["Floor"]] = relationship(
        "Floor",
        secondary=location_floors,
        back_populates="locations",
    )
    rules: Mapped[List["LocationRule"]] = relationship(
        "LocationRule",
        back_populates="location",
        cascade="all, delete-orphan",
    )


class LocationRule(Base):
    __tablename__ = "location_rules"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    capacity: Mapped[Optional[int]] = mapped_column(nullable=True)
    avaliable_days: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    start_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'ACTIVE'"))
    validate: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))

    created_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    location: Mapped["Location"] = relationship(
        "Location",
        back_populates="rules",
    )
