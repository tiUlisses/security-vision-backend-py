# app/models/device_event.py
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, ForeignKey, JSON, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.device import Device
    from app.models.incident import Incident

class DeviceEvent(Base):
    __tablename__ = "device_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # tópico exato em que o evento veio (ex: rtls/cameras/howbe/PredioA/Andar1/camera/fixa02/faceCapture/events)
    topic: Mapped[str] = mapped_column(String(512), nullable=False, index=True)

    # analyticType / eventType que veio no payload (faceCapture, PeopleCounting, etc.)
    analytic_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # payload JSON bruto (event + meta)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    # quando o evento ocorreu (Timestamp / dateTime do payload, caindo pra now() se não tiver)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    device: Mapped["Device"] = relationship(
        back_populates="events",
    )


    incident: Mapped[Optional["Incident"]] = relationship(
        "Incident",
        back_populates="device_event",
        uselist=False,
    )