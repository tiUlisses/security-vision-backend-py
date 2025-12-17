# app/models/presence_session.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class PresenceSession(Base):
    """
    View somente leitura baseada em collection_logs.

    Cada linha representa uma "sessão de presença" de uma TAG em um DEVICE.
    """

    __tablename__ = "presence_sessions"

    # id vem da MIN(id) dos collection_logs daquela sessão (na view)
    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    device_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    tag_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)

    started_at: Mapped[datetime] = mapped_column(nullable=False)
    ended_at: Mapped[datetime] = mapped_column(nullable=False)

    # duração da sessão em segundos
    duration_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # quantos pings (collection_logs) compõem a sessão
    samples_count: Mapped[int] = mapped_column(Integer, nullable=False)
