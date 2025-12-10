# app/crud/collection_log.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.collection_log import CollectionLog
from app.schemas.collection_log import CollectionLogCreate, CollectionLogUpdate


class CRUDCollectionLog(CRUDBase[CollectionLog, CollectionLogCreate, CollectionLogUpdate]):
    async def get_last_for_tag(
        self,
        db: AsyncSession,
        tag_id: int,
    ) -> CollectionLog | None:
        stmt = (
            select(self.model)
            .where(self.model.tag_id == tag_id)
            .order_by(self.model.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalars().first()


collection_log = CRUDCollectionLog(CollectionLog)
