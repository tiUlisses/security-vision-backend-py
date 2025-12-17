# app/schemas/incident_message.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class IncidentMessageBase(BaseModel):
    incident_id: int
    message_type: str = Field("TEXT", max_length=32)
    content: str = Field(..., max_length=8000)

    # 🔹 NOVO: campos opcionais para mídia
    media_type: Optional[str] = Field(None, max_length=32)  # IMAGE, VIDEO, AUDIO, FILE
    media_url: Optional[str] = None
    media_thumb_url: Optional[str] = None
    media_name: Optional[str] = Field(None, max_length=255)


class IncidentMessageCreate(BaseModel):
    """
    Body para criar mensagem na timeline.

    incident_id vem pela rota (/incidents/{id}/messages).
    """
    message_type: str = Field("TEXT", max_length=32)
    content: str = Field(..., max_length=8000)
    author_name: Optional[str] = None   
    media_type: Optional[str] = Field(None, max_length=32)
    media_url: Optional[str] = None
    media_thumb_url: Optional[str] = None
    media_name: Optional[str] = Field(None, max_length=255)


class IncidentMessageRead(BaseModel):
    id: int
    incident_id: int
    message_type: str
    content: Optional[str] = None

    media_type: Optional[str] = None
    media_url: Optional[str] = None
    media_thumb_url: Optional[str] = None
    media_name: Optional[str] = None

    # 👇 NOVO
    author_name: Optional[str] = None

    created_at: datetime

    class Config:
        from_attributes = True