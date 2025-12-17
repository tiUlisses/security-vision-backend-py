#securityvision-position/app/models/person.py
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.tag import Tag
    from app.models.person_group import PersonGroup

class Person(Base):
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    document_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    notes: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    tags: Mapped[List["Tag"]] = relationship(
        back_populates="person",
        cascade="all, delete-orphan",
    )
    groups: Mapped[List["PersonGroup"]] = relationship(
        secondary="person_group_memberships",
        back_populates="people",
    )