# app/crud/presence_session.py
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.presence_session import PresenceSession


class CRUDPresenceSession:
    """
    CRUD read-only para a view presence_sessions.
    """

    async def get(
        self,
        db: AsyncSession,
        id: int,
    ) -> Optional[PresenceSession]:
        stmt = select(PresenceSession).where(PresenceSession.id == id)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
        device_id: int | None = None,
        tag_id: int | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> List[PresenceSession]:
        stmt = select(PresenceSession)

        if device_id is not None:
            stmt = stmt.where(PresenceSession.device_id == device_id)
        if tag_id is not None:
            stmt = stmt.where(PresenceSession.tag_id == tag_id)
        if from_ts is not None:
            stmt = stmt.where(PresenceSession.started_at >= from_ts)
        if to_ts is not None:
            stmt = stmt.where(PresenceSession.ended_at <= to_ts)

        stmt = stmt.order_by(PresenceSession.started_at.desc())
        stmt = stmt.offset(skip).limit(limit)

        res = await db.execute(stmt)
        return list(res.scalars().all())


presence_session = CRUDPresenceSession()
