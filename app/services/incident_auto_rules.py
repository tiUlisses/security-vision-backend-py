# app/services/incident_auto_rules.py
from __future__ import annotations

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

async def apply_incident_rules_for_event(
    db: AsyncSession,
    *,
    event: "DeviceEvent",
) -> List["Incident"]:
    """
    Avalia as regras de incidente para um DeviceEvent de câmera e,
    se houver regra compatível, cria automaticamente incidentes
    + mensagens (SYSTEM + MEDIA a partir do snapshot da câmera).
    """

    print(f"[incident_rules] Avaliando regras para DeviceEvent id={event.id}, analytic_type={event.analytic_type}, device_id={event.device_id}")

    # 0) Se já existe incidente ligado a esse evento, não faz nada
    existing = await crud_incident.get_by_device_event(
        db,
        device_event_id=event.id,
    )
    if existing:
        print(f"[incident_rules] Já existe incidente para device_event_id={event.id} (incident_id={existing.id}), não vou criar outro.")
        return []

    # 1) garante que o device existe
    device = await crud_device.get(db, id=event.device_id)
    if not device:
        print(f"[incident_rules] Device id={event.device_id} não encontrado, abortando.")
        return []

    # 2) Busca regras compatíveis com ESTE evento (seu CRUD atual)
    rules = await crud_incident_rule.list_matching_event(db, event=event)
    print(f"[incident_rules] Encontradas {len(rules)} regras compatíveis para o evento {event.id}.")
    if not rules:
        return []

    payload = event.payload or {}
    tenant_from_event = None
    if isinstance(payload, dict):
        tenant_from_event = payload.get("tenant")

    incidents: List["Incident"] = []

    for rule in rules:
        print(
            f"[incident_rules] Aplicando regra id={rule.id}, "
            f"name='{rule.name}' ao evento {event.id}"
        )

        # 🔹 Pega o group_id de forma segura (não quebra se o atributo não existir)
        group_id = getattr(rule, "assigned_group_id", None)
        print(f"[incident_rules] rule.id={rule.id} assigned_group_id={group_id}")

        severity = (rule.severity or "MEDIUM").upper()
        kind = infer_incident_kind_from_event(event)

        # ----------------------------
        # SLA: se a regra tiver grupo, tenta usar o default_sla_minutes do grupo
        # ----------------------------
        now = datetime.now(timezone.utc)
        group_default_sla: int | None = None

        if group_id:
            sg = await crud_support_group.get(db, id=group_id)
            if sg:
                print(
                    f"[incident_rules] Suporte group id={group_id} "
                    f"default_sla_minutes={sg.default_sla_minutes}"
                )
                if sg.default_sla_minutes:
                    group_default_sla = sg.default_sla_minutes

        sla_minutes, due_at = compute_sla_fields(
            severity=severity,
            sla_minutes=group_default_sla,  # se None, cai no default global por severidade
            now=now,
        )

        camera_name = getattr(device, "name", None) or f"CAM {device.id}"

        # ---------- título / descrição com templates ----------

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

        default_title = f"[AUTO] {event.analytic_type} na câmera {camera_name}"
        title = render(rule.title_template, default_title)

        default_description = (
            f"Incidente criado automaticamente pela regra '{rule.name}' "
            f"ao receber o evento {event.id} ({event.analytic_type}) "
            f"da câmera {camera_name}."
        )
        description = render(rule.description_template, default_description)

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
            # atribuição automática
            "assigned_to_user_id": rule.assigned_to_user_id,
        }

        # Só adiciona se realmente tiver grupo
        if group_id:
            data["assigned_group_id"] = group_id

        # remove chaves com None
        data = {k: v for k, v in data.items() if v is not None}

        incident = await crud_incident.create(db, obj_in=data)
        incidents.append(incident)
            # 🔹 Dispara notificação inicial / criação da conversa no Chatwoot
        try:
            cw = ChatwootClient()
            await cw.send_incident_notification(
                incident=incident,
                incident_url=f"incident:{incident.id}",
            )
        except Exception as exc:
            print(
                f"[chatwoot] erro ao enviar notificação para incidente "
                f"{incident.id}: {exc}"
            )

        # ------------------------
        # Mensagem SYSTEM de contexto
        # ------------------------
        lines: list[str] = []

        lines.append(
            f"Incidente criado automaticamente pela regra **{rule.name}** "
            f"para o evento **{event.analytic_type}** na câmera "
            f"**{camera_name}**."
        )

        ts_raw = (
            payload.get("Timestamp")
            or payload.get("timestamp")
            or event.occurred_at
            or event.created_at
        )
        if ts_raw:
            if isinstance(ts_raw, str):
                ts_str = ts_raw
            else:
                ts_str = ts_raw.isoformat()
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
                lines.append(
                    f"Confiança do match: {(ff_confidence * 100):.1f}%."
                )

        lines.append(f"Severidade: **{severity}**. Status inicial: **OPEN**.")

        if group_id:
            lines.append(
                "Incidente atribuído automaticamente ao grupo de atendimento "
                "configurado na regra."
            )
        elif rule.assigned_to_user_id:
            lines.append(
                "Incidente atribuído automaticamente ao operador configurado na regra."
            )

        system_msg_data = {
            "incident_id": incident.id,
            "message_type": "SYSTEM",
            "content": "\n".join(lines),
            "author_name": "Sistema (regra de incidente)",
        }
        await crud_incident_message.create(db, obj_in=system_msg_data)

        # ------------------------
        # Mídias (snapshot, face cadastrada, etc.)
        # ------------------------
        media_descriptors = extract_media_from_event(event)
        # esperado: [{"source_url": "...", "filename_hint": "...", "label": "..."}]

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
            except Exception as exc:
                print(
                    f"[incident-rules] Falha ao baixar mídia '{url}' "
                    f"para incidente {incident.id}: {exc}"
                )
                continue

            msg_data = {
                "incident_id": incident.id,
                "message_type": "MEDIA",
                "media_type": media_type or "IMAGE",
                "media_url": media_url,
                "media_thumb_url": None,
                "media_name": original_name,
                "content": media.get("label"),
                "author_name": "Sistema (regra de incidente)",
            }
            await crud_incident_message.create(db, obj_in=msg_data)

    return incidents