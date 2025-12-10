from app.crud.base import CRUDBase
from app.models.floor import Floor
from app.schemas.floor import FloorCreate, FloorUpdate


class CRUDFloor(CRUDBase[Floor, FloorCreate, FloorUpdate]):
    pass


floor = CRUDFloor(Floor)
