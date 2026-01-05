from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class PresenceDailyUsage(Base):
    __tablename__ = "presence_daily_usage"

    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    )
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        primary_key=True,
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)

    total_dwell_seconds: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    sessions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    samples_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


Index(
    "ix_presence_daily_usage_day",
    PresenceDailyUsage.day,
)
