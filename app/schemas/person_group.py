#securityvision-position/app/schemas/person_group.py
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field

from app.schemas.person import PersonRead 

class PersonGroupBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = Field(None, max_length=1024)


class PersonGroupCreate(PersonGroupBase):
    pass


class PersonGroupUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=1024)


class PersonGroupRead(PersonGroupBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PersonGroupWithMembers(PersonGroupRead):
    """Resposta completa: grupo + lista de pessoas."""
    people: List[PersonRead]


class PersonGroupMembersUpdate(BaseModel):
    """Payload para definir os membros do grupo."""
    people_ids: List[int] = Field(
        ...,
        description="Lista de IDs de pessoas que devem pertencer ao grupo",
    )

