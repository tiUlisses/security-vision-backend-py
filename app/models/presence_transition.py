# app/models/presence_transition.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class PresenceTransition(Base):
    """
    View somente leitura baseada em presence_sessions.

    Cada linha representa a transição entre duas sessões consecutivas de uma TAG.
    """

    __tablename__ = "presence_transitions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    tag_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)

    from_session_id: Mapped[int] = mapped_column(Integer, nullable=False)
    to_session_id: Mapped[int] = mapped_column(Integer, nullable=False)

    from_device_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    to_device_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)

    transition_start_at: Mapped[datetime] = mapped_column(nullable=False)
    transition_end_at: Mapped[datetime] = mapped_column(nullable=False)
    transition_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
