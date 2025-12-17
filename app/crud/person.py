from app.crud.base import CRUDBase
from app.models.person import Person
from app.schemas.person import PersonCreate, PersonUpdate


class CRUDPerson(CRUDBase[Person, PersonCreate, PersonUpdate]):
    pass


person = CRUDPerson(Person)
