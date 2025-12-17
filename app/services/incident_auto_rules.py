# app/services/incident_auto_rules.py
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, TYPE_CHECKING
from app.services.chatwoot_client import ChatwootClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings

from app.crud import (
    device as crud_device,
    incident as crud_incident,
    incident_message as crud_incident_message,
    incident_rule as crud_incident_rule,
    support_group as crud_support_group,
)
from app.services.incident_files import save_incident_image_from_url
from app.services.incidents import (
    compute_sla_fields,
    infer_incident_kind_from_event,
    extract_media_from_event,
)

if TYPE_CHECKING:
    from app.models.device_event import DeviceEvent
    from app.models.incident import Incident



chatwoot_client = ChatwootClient()
logger = logging.getLogger(__name__)

async def apply_incident_rules_for_event(
    db: AsyncSession,
    *,
    event: "DeviceEvent",
) -> List["Incident"]:
    logger.info(
        "[incident_rules] avaliando regras para DeviceEvent id=%s analytic_type=%s device_id=%s",
        event.id,
        event.analytic_type,
        event.device_id,
    )

    existing = await crud_incident.get_by_device_event(db, device_event_id=event.id)
    if existing:
        logger.info(
            "[incident_rules] já existe incidente para device_event_id=%s (incident_id=%s)",
            event.id,
            existing.id,
        )
        return []

    device = await crud_device.get(db, id=event.device_id)
    if not device:
        logger.warning("[incident_rules] device id=%s não encontrado, abortando.", event.device_id)
        return []

    rules = await crud_incident_rule.list_matching_event(db, event=event)
    logger.info("[incident_rules] encontradas %s regras compatíveis para evento %s", len(rules), event.id)
    if not rules:
        return []

    payload = event.payload or {}
    tenant_from_event = payload.get("tenant") if isinstance(payload, dict) else None

    incidents: List["Incident"] = []

    for rule in rules:
        group_id = getattr(rule, "assigned_group_id", None)
        logger.info("[incident_rules] regra id=%s name=%r assigned_group_id=%r", rule.id, rule.name, group_id)

        severity = (rule.severity or "MEDIUM").upper()
        kind = infer_incident_kind_from_event(event)

        now = datetime.now(timezone.utc)

        # Se tiver grupo, pegamos o SupportGroup (e aproveitamos SLA default)
        sg = None
        group_default_sla: int | None = None
        if group_id:
            sg = await crud_support_group.get(db, id=group_id)
            if sg:
                group_default_sla = sg.default_sla_minutes or None
                logger.info(
                    "[incident_rules] support_group id=%s name=%r default_sla_minutes=%r",
                    sg.id,
                    getattr(sg, "name", None),
                    sg.default_sla_minutes,
                )
            else:
                logger.warning("[incident_rules] support_group id=%s não encontrado", group_id)

        sla_minutes, due_at = compute_sla_fields(
            severity=severity,
            sla_minutes=group_default_sla,
            now=now,
        )

        camera_name = getattr(device, "name", None) or f"CAM {device.id}"

        ctx: Dict[str, Any] = {
            "analytic_type": event.analytic_type,
            "camera_name": camera_name,
            "rule_name": rule.name,
            "device_id": device.id,
            "device_code": getattr(device, "code", None),
        }

        def render(template: str | None, default: str) -> str:
            if not template:
                return default
            try:
                return template.format(**ctx)
            except Exception:
                return default

        title = render(rule.title_template, f"[AUTO] {event.analytic_type} na câmera {camera_name}")
        description = render(
            rule.description_template,
            (
                f"Incidente criado automaticamente pela regra '{rule.name}' "
                f"ao receber o evento {event.id} ({event.analytic_type}) "
                f"da câmera {camera_name}."
            ),
        )

        data = {
            "device_id": event.device_id,
            "device_event_id": event.id,
            "kind": kind,
            "tenant": tenant_from_event or rule.tenant,
            "status": "OPEN",
            "severity": severity,
            "title": title,
            "description": description,
            "sla_minutes": sla_minutes,
            "due_at": due_at,
            "assigned_to_user_id": rule.assigned_to_user_id,
        }

        if group_id:
            data["assigned_group_id"] = group_id

        data = {k: v for k, v in data.items() if v is not None}

        incident = await crud_incident.create(db, obj_in=data)
        if group_id:
            sg = await crud_support_group.get(db, id=group_id)
            if sg:
                incident.assigned_group = sg  # atribui em memória pra roteamento

        # agora sim notifica
        try:
            await chatwoot_client.send_incident_notification(
                incident=incident,
                incident_url=f"{settings.CHATWOOT_INCIDENT_BASE_URL.rstrip('/')}/{incident.id}" if settings.CHATWOOT_INCIDENT_BASE_URL else None,
            )
        except Exception as exc:
            logger.exception("[chatwoot] erro ao enviar notificação incidente %s: %s", incident.id, exc)
        incidents.append(incident)

        # ✅ CRÍTICO: garantir que o Chatwoot consiga resolver inbox/time do grupo
        # ChatwootClient usa incident.assigned_group (obj), então “injetamos” o sg quando existir.
        if sg is not None:
            try:
                incident.assigned_group = sg  # type: ignore[attr-defined]
            except Exception:
                # best-effort
                pass

        # ✅ garante conversa no Chatwoot + persiste conversation_id no incidente
        if chatwoot_client.is_configured():
            try:
                conv_id = await chatwoot_client.send_incident_notification(incident=incident)
                if conv_id and conv_id != getattr(incident, "chatwoot_conversation_id", None):
                    incident = await crud_incident.update(
                        db,
                        db_obj=incident,
                        obj_in={"chatwoot_conversation_id": conv_id},
                    )
                    # mantém em memória também (evita re-enviar resumo)
                    try:
                        incident.chatwoot_conversation_id = conv_id  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                logger.exception("[chatwoot] erro ao enviar notificação para incidente %s", incident.id)

        # ------------------------
        # SYSTEM (contexto) + envia pro Chatwoot
        # ------------------------
        lines: list[str] = []
        lines.append(
            f"Incidente criado automaticamente pela regra **{rule.name}** "
            f"para o evento **{event.analytic_type}** na câmera **{camera_name}**."
        )

        ts_raw = payload.get("Timestamp") or payload.get("timestamp") or event.occurred_at or event.created_at
        if ts_raw:
            ts_str = ts_raw if isinstance(ts_raw, str) else ts_raw.isoformat()
            lines.append(f"Horário do evento: {ts_str}.")

        building = payload.get("Building")
        floor = payload.get("Floor")
        meta = payload.get("Meta") or {}
        ff_name = meta.get("ff_person_name") or meta.get("person_name")
        ff_confidence = meta.get("ff_confidence")

        if building or floor:
            partes = []
            if building:
                partes.append(f"Prédio: {building}")
            if floor:
                partes.append(f"Andar/Setor: {floor}")
            lines.append("Local: " + " • ".join(partes) + ".")

        if ff_name:
            lines.append(f"Pessoa reconhecida: **{ff_name}**.")
            if isinstance(ff_confidence, (int, float)):
                lines.append(f"Confiança do match: {(ff_confidence * 100):.1f}%.")

        lines.append(f"Severidade: **{severity}**. Status inicial: **OPEN**.")

        if group_id:
            lines.append("Incidente atribuído automaticamente ao grupo configurado na regra.")
        elif rule.assigned_to_user_id:
            lines.append("Incidente atribuído automaticamente ao operador configurado na regra.")

        system_msg = await crud_incident_message.create(
            db,
            obj_in={
                "incident_id": incident.id,
                "message_type": "SYSTEM",
                "content": "\n".join(lines),
                "author_name": "Sistema (regra de incidente)",
            },
        )

        if chatwoot_client.is_configured():
            try:
                await chatwoot_client.send_incident_timeline_message(incident, system_msg)
            except Exception:
                logger.exception("[chatwoot] erro ao enviar SYSTEM incidente=%s msg=%s", incident.id, system_msg.id)

        # ------------------------
        # MEDIA (snapshot, face etc.) + envia pro Chatwoot
        # ------------------------
        media_descriptors = extract_media_from_event(event)

        for media in media_descriptors:
            url = media.get("source_url")
            if not url:
                continue

            try:
                media_url, media_type, original_name = await save_incident_image_from_url(
                    incident_id=incident.id,
                    url=url,
                    filename_hint=media.get("filename_hint"),
                )
            except Exception:
                logger.exception(
                    "[incident_rules] falha ao baixar mídia url=%r incidente=%s",
                    url,
                    incident.id,
                )
                continue

            media_msg = await crud_incident_message.create(
                db,
                obj_in={
                    "incident_id": incident.id,
                    "message_type": "MEDIA",
                    "media_type": media_type or "IMAGE",
                    "media_url": media_url,
                    "media_thumb_url": None,
                    "media_name": original_name,
                    "content": media.get("label"),
                    "author_name": "Sistema (regra de incidente)",
                },
            )

            if chatwoot_client.is_configured():
                try:
                    await chatwoot_client.send_incident_timeline_message(incident, media_msg)
                except Exception:
                    logger.exception(
                        "[chatwoot] erro ao enviar MEDIA incidente=%s msg=%s url=%r",
                        incident.id,
                        media_msg.id,
                        media_url,
                    )

    return incidents