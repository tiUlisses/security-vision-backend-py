#securityvision-position/app/crud/person_group.py
from app.crud.base import CRUDBase
from app.models.person_group import PersonGroup
from app.schemas.person_group import PersonGroupCreate, PersonGroupUpdate


class CRUDPersonGroup(CRUDBase[PersonGroup, PersonGroupCreate, PersonGroupUpdate]):
    pass


person_group = CRUDPersonGroup(PersonGroup)
