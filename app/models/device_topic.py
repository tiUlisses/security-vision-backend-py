# app/models/device_topic.py
from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import ForeignKey, String, text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.device import Device


class DeviceTopic(Base):
    __tablename__ = "device_topics"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Ex.: "cambus_info", "cambus_event", "collector_status", etc.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)

    # Tópico MQTT completo, ex.:
    # rtls/cameras/howbe/PredioA/Andar1/camera/fixa02/info
    topic: Mapped[str] = mapped_column(String(512), nullable=False)

    description: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
    )

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

    device: Mapped["Device"] = relationship(
        "Device",
        back_populates="topics",
    )
