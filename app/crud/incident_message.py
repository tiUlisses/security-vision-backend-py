# app/crud/incident_message.py
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.incident_message import IncidentMessage
from app.schemas.incident_message import IncidentMessageCreate


class CRUDIncidentMessage(
    CRUDBase[IncidentMessage, IncidentMessageCreate, None]
):
    async def list_by_incident(
        self,
        db: AsyncSession,
        *,
        incident_id: int,
        limit: int = 200,
    ) -> List[IncidentMessage]:
        stmt = (
            select(self.model)
            .where(self.model.incident_id == incident_id)
            .order_by(self.model.created_at.asc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()


incident_message = CRUDIncidentMessage(IncidentMessage)
