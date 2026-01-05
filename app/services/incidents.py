# app/services/incidents.py
from __future__ import annotations
import logging
from app.services.chatwoot_client import ChatwootClient
from app.services.webhook_dispatcher import dispatch_generic_webhook
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

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

logger = logging.getLogger(__name__)


# 🔹 SLA padrão por severidade (em minutos)
DEFAULT_SLA_BY_SEVERITY: dict[str, int] = {
    "CRITICAL": 15,
    "HIGH": 60,
    "MEDIUM": 240,
    "LOW": 1440,
}


def build_incident_webhook_payload(
    incident: Incident,
    *,
    previous_status: Optional[str] = None,
) -> Dict[str, Any]:
    def _to_iso(value: Optional[datetime]) -> Optional[str]:
        return value.isoformat() if value else None

    return {
        "incident_id": incident.id,
        "status": incident.status,
        "previous_status": previous_status,
        "severity": incident.severity,
        "title": incident.title,
        "device_id": incident.device_id,
        "device_event_id": incident.device_event_id,
        "assigned_group_id": incident.assigned_group_id,
        "assigned_to_user_id": incident.assigned_to_user_id,
        "kind": incident.kind,
        "tenant": incident.tenant,
        "sla_minutes": incident.sla_minutes,
        "due_at": _to_iso(incident.due_at),
        "created_at": _to_iso(incident.created_at),
        "updated_at": _to_iso(incident.updated_at),
        "closed_at": _to_iso(incident.closed_at),
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


def _guess_media_type_from_url(url: str) -> str:
    """Tenta inferir o tipo de mídia só pela extensão da URL."""
    lower = url.lower()
    if lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return "IMAGE"
    if lower.endswith((".mp4", ".mkv", ".mov", ".avi", ".webm")):
        return "VIDEO"
    if lower.endswith((".mp3", ".wav", ".ogg")):
        return "AUDIO"
    return "FILE"


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

    if new_status != old_status:
        content = f"Status alterado de {old_status} para {new_status}."
        msg_data = {
            "incident_id": updated.id,
            "message_type": "SYSTEM",
            "content": content,
        }
        db_msg = await crud_incident_message.create(db, obj_in=msg_data)

        # 🔹 envia também pro Chatwoot
        try:
            client = ChatwootClient()
            await client.send_incident_timeline_message(
                updated,
                db_msg,
            )
        except Exception:
            logger.exception(
                "[chatwoot] erro ao enviar mensagem de status do incidente %s",
                updated.id,
            )

        event_type = "INCIDENT_STATUS_CHANGED"
        if (
            old_status in TERMINAL_STATUSES
            and new_status in ACTIVE_STATUSES
        ):
            event_type = "INCIDENT_REOPENED"

        await dispatch_generic_webhook(
            db,
            event_type=event_type,
            payload=build_incident_webhook_payload(
                updated,
                previous_status=old_status,
            ),
        )

    return updated


def extract_media_from_event(event: DeviceEvent) -> list[dict]:
    """
    Monta UMA OU MAIS mensagens de mídia a partir do payload do DeviceEvent.

    - Para FaceRecognized: 1 msg com snapshot, 1 msg com foto cadastrada (se houver).
    - Para demais tipos: 1 msg com snapshot (se houver).
    - NÃO faz download das imagens; apenas referencia as URLs (MinIO, etc.).
    """
    payload: Dict[str, Any] = event.payload or {}
    meta: Dict[str, Any] = payload.get("Meta") or {}
    messages: List[Dict[str, Any]] = []

    analytic = (
        payload.get("AnalyticType")
        or event.analytic_type
        or "evento de câmera"
    )

    # Timestamp do evento (deixa como string mesmo, sem parse complicado)
    ts_raw = (
        payload.get("Timestamp")
        or payload.get("timestamp")
        or getattr(event, "occurred_at", None)
        or getattr(event, "created_at", None)
    )
    ts_label = str(ts_raw) if ts_raw is not None else ""

    # URLs de mídia vindas do payload
    snapshot_url = (
        payload.get("SnapshotURL")
        or payload.get("snapshotUrl")
        or payload.get("snapshot_url")
    )

    ff_photo_url = meta.get("ff_person_photo_url")
    ff_name = meta.get("ff_person_name") or meta.get("person_name") or None
    ff_conf = meta.get("ff_confidence")

    analytic_lower = str(analytic).lower()
    is_face_recognized = analytic_lower in {
        "facerecognized",
        "face_recognized",
        "face recognized",
    }

    # 1) Snapshot geral do evento
    if snapshot_url:
        if is_face_recognized:
            # Template mais rico para reconhecimento facial
            conf_txt = ""
            if isinstance(ff_conf, (int, float)):
                conf_txt = f" ({ff_conf * 100:.1f}% de confiança)"

            person_txt = ff_name or "Pessoa não identificada"
            content = (
                f"Reconhecimento facial: {person_txt}{conf_txt}. "
                f"Analítico: {analytic}. "
            )
        else:
            content = f"Evento de câmera: {analytic}. "

        if ts_label:
            content += f"Horário do evento: {ts_label}."

        messages.append(
            {
                "message_type": "MEDIA",
                "content": content,
                "media_type": _guess_media_type_from_url(snapshot_url),
                "media_url": snapshot_url,
                "media_thumb_url": snapshot_url,
                "media_name": "snapshot_evento",
                "author_name": "Sistema (evento de câmera)",
            }
        )

    # 2) Foto cadastrada da pessoa (se houver, e se for FaceRecognized)
    if is_face_recognized and ff_photo_url:
        person_txt = ff_name or "Pessoa reconhecida"
        content = f"Face cadastrada de referência para {person_txt}."

        messages.append(
            {
                "message_type": "MEDIA",
                "content": content,
                "media_type": _guess_media_type_from_url(ff_photo_url),
                "media_url": ff_photo_url,
                "media_thumb_url": ff_photo_url,
                "media_name": "face_cadastrada",
                "author_name": "Sistema (evento de câmera)",
            }
        )

    return messages

def _safe_parse_payload(payload: Any) -> Dict[str, Any]:
    """Garante que o payload seja um dict."""
    if not payload:
        return {}
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:
            return {}
    return {}

def _extract_timestamp_label(event: DeviceEvent, payload: Dict[str, Any]) -> str:
    """
    Tenta pegar um timestamp amigável do payload/evento.
    """
    ts_raw = (
        payload.get("Timestamp")
        or payload.get("timestamp")
        or getattr(event, "occurred_at", None)
        or getattr(event, "created_at", None)
    )

    if isinstance(ts_raw, str):
        return ts_raw

    if isinstance(ts_raw, datetime):
        return ts_raw.isoformat(timespec="seconds")

    return ""

def extract_media_from_event(event: DeviceEvent) -> List[Dict[str, Any]]:
    """
    Analisa o payload do DeviceEvent e retorna uma lista de descrições de mídias
    a serem anexadas ao incidente.

    Cada item do retorno tem a forma:
      {
        "source_url": str,        # URL original da imagem (snapshot, face, etc.)
        "label": str,             # texto da mensagem na timeline
        "filename_hint": str|None # nome sugerido do arquivo (opcional)
      }
    """
    payload: Dict[str, Any] = event.payload or {}
    meta: Dict[str, Any] = payload.get("Meta") or {}

    result: List[Dict[str, Any]] = []

    ts_label = _extract_timestamp_label(event, payload)
    analytic = (payload.get("AnalyticType") or event.analytic_type or "").strip()
    analytic_lower = analytic.lower()

    # 1) Snapshot do evento (qualquer analítico que traga snapshot)
    snapshot_url = (
        payload.get("SnapshotURL")
        or payload.get("snapshotUrl")
        or payload.get("snapshot_url")
    )

    if snapshot_url:
        label = f"Snapshot do evento {analytic}"
        if ts_label:
            label += f" às {ts_label}"

        result.append(
            {
                "source_url": snapshot_url,
                "label": label,
                "filename_hint": "snapshot_evento.jpg",
            }
        )

    # 2) Face reconhecida: foto cadastrada da pessoa
    ff_photo_url = meta.get("ff_person_photo_url") or meta.get(
        "person_photo_url"
    )
    ff_name = meta.get("ff_person_name") or meta.get("person_name")
    ff_conf = meta.get("ff_confidence") or meta.get("confidence")

    is_face_recognized = analytic_lower in {
        "facerecognized",
        "face_recognized",
        "face recognized",
    }

    if ff_photo_url and is_face_recognized:
        if isinstance(ff_conf, (int, float)):
            conf_str = f"{ff_conf * 100:.1f}%"
        else:
            conf_str = None

        person_label = ff_name or "Pessoa reconhecida"

        label = f"Face cadastrada: {person_label}"
        if conf_str:
            label += f" ({conf_str})"
        if ts_label:
            label += f" às {ts_label}"

        result.append(
            {
                "source_url": ff_photo_url,
                "label": label,
                "filename_hint": "face_cadastrada.jpg",
            }
        )

    return result

    # ------------------------------------------------------------------
    # 1) Mensagem com SNAPSHOT do evento (para QUALQUER analítico)
    # ------------------------------------------------------------------
    if snapshot_url:
        parts: List[str] = []

        if analytic:
            parts.append(f"Evento {analytic}")
        if camera_name:
            parts.append(f"na câmera {camera_name}")
        if floor:
            parts.append(f"no setor/andar {floor}")
        if building:
            parts.append(f"no prédio {building}")
        if ts_label:
            parts.append(f"às {ts_label}")

        content = " ".join(parts) or "Snapshot do evento da câmera."

        messages.append(
            {
                "message_type": "MEDIA",
                "content": content,
                "media_type": "IMAGE",
                "media_url": snapshot_url,
                "media_thumb_url": None,
                "media_name": "snapshot_evento",
            }
        )

    # ------------------------------------------------------------------
    # 2) Caso seja reconhecimento facial: foto cadastrada + texto rico
    # ------------------------------------------------------------------
    analytic_lower = (analytic or "").lower()
    is_face_recognized = analytic_lower in {
        "facerecognized",
        "face_recognized",
        "face recognized",
        "face_recognition",
    }

    if is_face_recognized and ff_photo_url:
        if ff_name:
            base_text = f"Face reconhecida: {ff_name}"
        else:
            base_text = "Face reconhecida"

        if isinstance(ff_conf, (int, float)):
            # se vier em [0,1], converte pra %
            conf_val = ff_conf * 100 if ff_conf <= 1 else ff_conf
            base_text += f" (confiança {conf_val:.1f}%)"

        if camera_name and ts_label:
            base_text += f" na câmera {camera_name} às {ts_label}."
        elif camera_name:
            base_text += f" na câmera {camera_name}."
        elif ts_label:
            base_text += f" às {ts_label}."

        messages.append(
            {
                "message_type": "MEDIA",
                "content": base_text,
                "media_type": "IMAGE",
                "media_url": ff_photo_url,
                "media_thumb_url": None,
                "media_name": ff_name or "face_cadastrada",
            }
        )

    if not messages:
        return None

    return messages
