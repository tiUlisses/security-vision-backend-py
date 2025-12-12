# app/schemas/user.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(..., max_length=255)
    role: str = Field("OPERATOR", max_length=32)
    is_active: bool = True
    is_superuser: bool = False
    

class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=128)


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=255)
    role: Optional[str] = Field(None, max_length=32)
    is_active: Optional[bool] = None
    chatwoot_agent_id: Optional[int] = None   # 🔹 novo

class UserRead(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime
    chatwoot_agent_id: Optional[int] = None   # 🔹 novo

    class Config:
        from_attributes = True



# 🔹 RESUMO PARA RELAÇÕES (Incidents, SupportGroups, etc.)
class UserShort(BaseModel):
    id: int
    full_name: str
    email: EmailStr

    class Config:
        from_attributes = True

# --- Auth / JWT ---


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: int
    exp: int
    role: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
