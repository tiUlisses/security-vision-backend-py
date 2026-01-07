# app/models/device.py
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, String, Integer, text, Column, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.floor_plan import FloorPlan
    from app.models.collection_log import CollectionLog
    from app.models.alert_rule import AlertRule
    from app.models.building import Building
    from app.models.floor import Floor
    from app.models.device_event import DeviceEvent  # 👈 novo
    from app.models.incident import Incident


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # planta baixa (opcional) – já existia
    floor_plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("floor_plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # NOVO: associação lógica a prédio / andar
    building_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("buildings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    floor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("floors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Comum a todos os devices
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
        index=True,
    )
    type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="BLE_GATEWAY",
    )
    mac_address: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # Posição na planta
    pos_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pos_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # NOVO: campos de rede (principalmente para CAMERA / ACCESS_CONTROLLER)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    password: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    rtsp_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    proxy_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    central_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    record_retention_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    central_media_mtx_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # NOVO: fabricante / modelo / shard do cam-bus
    manufacturer: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    shard: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    analytics = Column(JSON, nullable=True)
    # para cálculo de online/offline
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    # Relações
    floor_plan: Mapped[Optional["FloorPlan"]] = relationship(
        back_populates="devices",
    )

    building: Mapped[Optional["Building"]] = relationship("Building")
    floor: Mapped[Optional["Floor"]] = relationship("Floor")

    collection_logs: Mapped[List["CollectionLog"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
    )

    alert_rules: Mapped[List["AlertRule"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
    )

    topics: Mapped[List["DeviceTopic"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
    )


    collection_logs: Mapped[List["CollectionLog"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
    )

    alert_rules: Mapped[List["AlertRule"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
    )

    events: Mapped[List["DeviceEvent"]] = relationship(  # 👈 novo
        back_populates="device",
        cascade="all, delete-orphan",
    )

    events: Mapped[List["DeviceEvent"]] = relationship(
        "DeviceEvent",
        back_populates="device",
        cascade="all, delete-orphan",
    )

    topics: Mapped[List["DeviceTopic"]] = relationship(
        "DeviceTopic",
        back_populates="device",
        cascade="all, delete-orphan",
    )

    incidents: Mapped[List["Incident"]] = relationship(
        "Incident",
        back_populates="device",
        cascade="all, delete-orphan",
    )
    camera_groups = relationship(
        "CameraGroup",
        secondary="camera_group_devices",
        back_populates="devices",
        lazy="selectin",
    )
