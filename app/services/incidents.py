# app/services/incidents.py
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.models.device_event import DeviceEvent
from app.schemas.incident import IncidentUpdate
from app.crud import (
    incident as crud_incident,
    incident_message as crud_incident_message,
)

TERMINAL_STATUSES = {"RESOLVED", "FALSE_POSITIVE", "CANCELED"}
ACTIVE_STATUSES = {"OPEN", "IN_PROGRESS"}

# 🔹 SLA padrão por severidade (em minutos)
DEFAULT_SLA_BY_SEVERITY: dict[str, int] = {
    "CRITICAL": 15,
    "HIGH": 60,
    "MEDIUM": 240,
    "LOW": 1440,
}


def compute_sla_fields(
    *,
    severity: Optional[str],
    sla_minutes: Optional[int] = None,
    due_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> tuple[Optional[int], Optional[datetime]]:
    """
    Define sla_minutes e due_at com base na severidade e nos valores já enviados.

    - Se sla_minutes vier preenchido, respeitamos.
    - Senão, usamos o DEFAULT_SLA_BY_SEVERITY.
    - Se due_at vier preenchido, respeitamos.
    - Senão, calculamos due_at = now + sla_minutes.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    sev = (severity or "MEDIUM").upper()

    if sla_minutes is None:
        sla_minutes = DEFAULT_SLA_BY_SEVERITY.get(
            sev,
            DEFAULT_SLA_BY_SEVERITY["MEDIUM"],
        )

    if sla_minutes is not None and due_at is None:
        due_at = now + timedelta(minutes=sla_minutes)

    return sla_minutes, due_at


def infer_incident_kind_from_event(event: DeviceEvent) -> str:
    """
    Classifica o tipo de incidente a partir do analytic_type do evento.
    """
    at = (event.analytic_type or "").lower()

    # você pode deixar isso mais sofisticado depois
    if "offline" in at or "status" in at:
        return "CAMERA_OFFLINE"
    if "face" in at:
        return "CAMERA_FACE"
    if "intrusion" in at or "alarm" in at:
        return "CAMERA_INTRUSION"
    if "tamper" in at:
        return "CAMERA_TAMPER"

    return "CAMERA_EVENT"


async def apply_incident_update(
    db: AsyncSession,
    *,
    incident: Incident,
    update_in: IncidentUpdate,
    actor_user_id: Optional[int] = None,
) -> Incident:
    """
    Aplica alterações em um incidente (status, etc), centralizando regras de negócio.
    """
    update_data = update_in.model_dump(exclude_unset=True)

    old_status = incident.status
    new_status = update_data.get("status", old_status)

    # closed_at conforme status (terminal x ativo)
    if (
        new_status in TERMINAL_STATUSES
        and "closed_at" not in update_data
        and incident.closed_at is None
    ):
        update_data["closed_at"] = datetime.now(timezone.utc)

    if (
        new_status in ACTIVE_STATUSES
        and "closed_at" not in update_data
        and incident.closed_at is not None
    ):
        update_data["closed_at"] = None

    # Atualizamos o incidente
    updated = await crud_incident.update(
        db,
        db_obj=incident,
        obj_in=update_data,
    )

    # Se houve mudança de status, registramos mensagem de sistema
    if new_status != old_status:
        content = f"Status alterado de {old_status} para {new_status}."
        msg_data = {
            "incident_id": updated.id,
            "message_type": "SYSTEM",
            "content": content,
        }
        await crud_incident_message.create(db, obj_in=msg_data)

    return updated


def extract_media_from_event(event: DeviceEvent) -> Optional[dict]:
    """
    Tenta extrair informações de mídia do payload do evento.

    Convenções que podemos usar (ajustar conforme seu cambus):
    - payload["snapshot_url"]
    - payload["image_url"]
    - payload["snapshot_path"]
    - payload["image_path"]
    - payload["thumbnail_url"]

    Retorna um dict pronto para criar IncidentMessage ou None se não houver mídia.
    """
    payload = event.payload or {}
    if not isinstance(payload, dict):
        return None

    # tenta pegar URL direta
    snapshot_url = (
        payload.get("snapshot_url")
        or payload.get("image_url")
        or payload.get("snapshot")
    )

    # se não tiver URL, tenta path (ex.: caminho no bucket MinIO)
    if not snapshot_url:
        snapshot_url = payload.get("snapshot_path") or payload.get("image_path")

    if not snapshot_url:
        return None

    thumb_url = (
        payload.get("thumbnail_url")
        or payload.get("thumb_url")
    )

    media_name = (
        payload.get("file_name")
        or payload.get("snapshot_name")
        or f"snapshot-event-{event.id}.jpg"
    )

    return {
        "message_type": "MEDIA",
        "content": "Snapshot associado ao evento da câmera.",
        "media_type": "IMAGE",
        "media_url": snapshot_url,
        "media_thumb_url": thumb_url,
        "media_name": media_name,
    }