# app/models/incident_message.py
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.incident import Incident


class IncidentMessage(Base):
    """
    Mensagem da timeline de um incidente.

    Tipos principais:
    - TEXT   : mensagem de operador
    - SYSTEM : mensagem gerada automaticamente pelo sistema
    - MEDIA  : mensagem de mídia (imagem, vídeo, áudio, arquivo), com URL
    """

    __tablename__ = "incident_messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # "TEXT", "SYSTEM", "MEDIA", etc.
    message_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="TEXT",
    )

    # Conteúdo principal (texto)
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # 🔹 NOVO: informações de mídia (todos opcionais)
    # ex.: "IMAGE", "VIDEO", "AUDIO", "FILE"
    media_type: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
    )

    # URL acessível da mídia (MinIO, CDN, etc.)
    media_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # URL de thumbnail (se quiser, para imagens/vídeos)
    media_thumb_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # Nome amigável do arquivo
    media_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
        index=True,
    )

    incident: Mapped["Incident"] = relationship(
        "Incident",
        back_populates="messages",
    )
