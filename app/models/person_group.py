#securityvision-position/app/models/person_group.py
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Column, ForeignKey, String, Table, text
from sqlalchemy.orm import Mapped, mapped_column, relationship


from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.person import Person
    from app.models.alert_rule import AlertRule


person_group_memberships = Table(
    "person_group_memberships",
    Base.metadata,
    Column("person_id", ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("person_groups.id", ondelete="CASCADE"), primary_key=True),
)


class PersonGroup(Base):
    __tablename__ = "person_groups"   # <- NOME DA TABELA (igual ao FK)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    people: Mapped[List["Person"]] = relationship(
        "Person",
        secondary=person_group_memberships,
        back_populates="groups",
    )
    alert_rules: Mapped[List["AlertRule"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
    )
