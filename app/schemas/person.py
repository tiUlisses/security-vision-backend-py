#securityvision-position/app/schemas/person.py
from datetime import datetime
from typing import Optional

from pydantic import AliasChoices, BaseModel, Field, computed_field


class PersonBase(BaseModel):
    full_name: str = Field(..., max_length=255, validation_alias=AliasChoices("full_name", "name"))
    document_id: Optional[str] = Field(
        None,
        max_length=64,
        validation_alias=AliasChoices("document_id", "cpf"),
    )
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=32)
    user_type: Optional[int] = None
    active: bool = True
    notes: Optional[str] = Field(None, max_length=1024)


class PersonCreate(PersonBase):
    pass


class PersonUpdate(BaseModel):
    full_name: Optional[str] = Field(
        None,
        max_length=255,
        validation_alias=AliasChoices("full_name", "name"),
    )
    document_id: Optional[str] = Field(
        None,
        max_length=64,
        validation_alias=AliasChoices("document_id", "cpf"),
    )
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=32)
    user_type: Optional[int] = None
    active: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=1024)


class PersonRead(PersonBase):
    id: int
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def cpf(self) -> Optional[str]:
        return self.document_id

    @computed_field
    @property
    def status(self) -> str:
        return "ACTIVE" if self.active else "INACTIVE"

    class Config:
        from_attributes = True
