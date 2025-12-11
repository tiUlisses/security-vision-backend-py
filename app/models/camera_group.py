# app/models/camera_group.py
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class CameraGroup(Base):
    __tablename__ = "camera_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(String(1024), nullable=True)
    tenant = Column(String(255), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    devices = relationship(
        "Device",
        secondary="camera_group_devices",
        back_populates="camera_groups",
        lazy="selectin",
    )


class CameraGroupDevice(Base):
    __tablename__ = "camera_group_devices"

    camera_group_id = Column(
        Integer,
        ForeignKey("camera_groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # ⚠️ Se sua tabela de devices se chamar "device" e não "devices",
    # troque "devices.id" por "device.id" aqui:
    device_id = Column(
        Integer,
        ForeignKey("devices.id", ondelete="CASCADE"),
        primary_key=True,
    )
