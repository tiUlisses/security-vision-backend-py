# app/crud/tag.py
from sqlalchemy import select

from app.crud.base import CRUDBase
from app.models.tag import Tag
from app.schemas.tag import TagCreate, TagUpdate


class CRUDTag(CRUDBase[Tag, TagCreate, TagUpdate]):
    async def get_by_mac(self, db, mac_address: str) -> Tag | None:
        """Busca TAG pelo MAC sendo tolerante a formatos.

        O gateway pode mandar MAC sem separadores (12-hex) ou com ':' / '-'.
        O banco pode estar em qualquer um desses formatos.
        """
        from app.utils.mac import candidate_macs

        cands = candidate_macs(mac_address)
        if not cands:
            return None

        stmt = select(self.model).where(self.model.mac_address.in_(list(cands)))
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_by_person(self, db, person_id: int) -> list[Tag]:
        stmt = select(self.model).where(self.model.person_id == person_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())


tag = CRUDTag(Tag)
