# app/services/alert_engine.py

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Dict, Any

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.alert_event import AlertEventCreate
from app.crud.alert_rule import alert_rule as crud_alert_rule
from app.crud.alert_event import alert_event as crud_alert_event
from app.models.alert_rule import AlertRule
from app.models.alert_event import AlertEvent
from app.models.device import Device
from app.models.tag import Tag
from app.models.person import Person
from app.models.floor_plan import FloorPlan
from app.models.floor import Floor
from app.models.building import Building
from app.models.person_group import person_group_memberships
from app.services.webhook_dispatcher import dispatch_webhooks
from app.core.config import settings

logger = logging.getLogger("rtls.alert_engine")

# Tipos de regras RTLS
FORBIDDEN_SECTOR = "FORBIDDEN_SECTOR"
DWELL_TIME = "DWELL_TIME"

# Eventos sistêmicos
GATEWAY_OFFLINE = "GATEWAY_OFFLINE"
GATEWAY_ONLINE = "GATEWAY_ONLINE"

RTLS_SESSION_EVENT_TYPES = (FORBIDDEN_SECTOR, DWELL_TIME)


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def _ensure_utc(dt: datetime | None) -> datetime:
    """
    Garante datetime timezone-aware em UTC.
    """
    now = datetime.now(timezone.utc)
    if dt is None:
        return now
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _dt_iso(dt: datetime | None) -> Optional[str]:
    return _ensure_utc(dt).isoformat() if dt is not None else None


def _safe_json_load(s: str | None) -> Dict[str, Any]:
    if not s:
        return {}
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _safe_json_dump(d: Dict[str, Any]) -> str:
    return json.dumps(d, ensure_ascii=False)


def _get_session_ttl_seconds() -> int:
    """
    TTL para encerrar sessões RTLS quando não há novas evidências.

    - settings.ALERT_SESSION_TTL_SECONDS (se existir)
    - fallback: settings.POSITION_STALE_THRESHOLD_SECONDS * 2
    - fallback final: 60s
    """
    ttl = getattr(settings, "ALERT_SESSION_TTL_SECONDS", None)
    if isinstance(ttl, int) and ttl >= 0:
        return ttl

    pos_ttl = getattr(settings, "POSITION_STALE_THRESHOLD_SECONDS", None)
    if isinstance(pos_ttl, int) and pos_ttl > 0:
        return int(pos_ttl) * 2

    return 60


async def _close_event_session(
    db: AsyncSession,
    *,
    event: AlertEvent,
    reason: str,
) -> AlertEvent:
    """
    Fecha uma sessão de alerta RTLS, usando ended_at = last_seen_at (última evidência real).
    Atualiza payload com ended_at/is_open/duration e dispara webhook.
    """
    if not getattr(event, "is_open", False):
        return event

    last_seen = _ensure_utc(getattr(event, "last_seen_at", None))
    started = _ensure_utc(getattr(event, "started_at", None))
    ended_at = last_seen

    payload = _safe_json_load(getattr(event, "payload", None))
    payload.update(
        {
            "is_open": False,
            "ended_at": ended_at.isoformat(),
            "last_seen_at": last_seen.isoformat(),
            "started_at": started.isoformat(),
            "duration_seconds": max(0, (ended_at - started).total_seconds()),
            "close_reason": reason,
        }
    )

    updated = await crud_alert_event.update(
        db,
        event,
        {
            "is_open": False,
            "ended_at": ended_at,
            "payload": _safe_json_dump(payload),
        },
    )

    # Dispara webhook de update/fechamento
    try:
        await dispatch_webhooks(db, updated)
    except Exception:
        logger.exception("Failed to dispatch webhook on alert close (event_id=%s)", updated.id)

    return updated


async def close_stale_rtls_sessions(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    ttl_seconds: int | None = None,
    tag_id: int | None = None,
    device_id: int | None = None,
) -> int:
    """
    ETAPA 2: Fecha sessões RTLS (FORBIDDEN_SECTOR / DWELL_TIME) que ficaram "stale".

    Encerramento:
      - is_open=False
      - ended_at = last_seen_at (última evidência)
      - payload enriquecido

    Pode ser chamado:
      - oportunisticamente em process_detection (para reentradas)
      - periodicamente por algum loop do sistema (recomendado)
    """
    now = _ensure_utc(now)
    ttl = _get_session_ttl_seconds() if ttl_seconds is None else int(ttl_seconds)

    # ttl=0 -> desabilita fechamento automático por tempo
    if ttl <= 0:
        return 0

    cutoff = now - timedelta(seconds=ttl)

    stmt = select(AlertEvent).where(
        AlertEvent.is_open.is_(True),
        AlertEvent.event_type.in_(RTLS_SESSION_EVENT_TYPES),
        AlertEvent.last_seen_at < cutoff,
    )

    if tag_id is not None:
        stmt = stmt.where(AlertEvent.tag_id == tag_id)

    if device_id is not None:
        stmt = stmt.where(AlertEvent.device_id == device_id)

    res = await db.execute(stmt)
    events = list(res.scalars().all())

    closed = 0
    for ev in events:
        await _close_event_session(db, event=ev, reason=f"stale_ttl_{ttl}s")
        closed += 1

    if closed:
        logger.info("Closed %s stale RTLS sessions (ttl=%ss cutoff=%s)", closed, ttl, cutoff.isoformat())

    return closed


# ---------------------------------------------------------------------------
# Helpers de consulta (SEM lazy loading)
# ---------------------------------------------------------------------------

async def _get_person_with_groups(
    db: AsyncSession,
    *,
    tag: Tag,
) -> Tuple[Optional[Person], List[int]]:
    """
    Carrega a pessoa associada à TAG e os IDs dos grupos dessa pessoa,
    sem lazy-load.
    """
    person_id = getattr(tag, "person_id", None)
    if not person_id:
        return None, []

    stmt_person = select(Person).where(Person.id == person_id)
    res_person = await db.execute(stmt_person)
    person = res_person.scalars().first()
    if not person:
        return None, []

    stmt_groups = select(person_group_memberships.c.group_id).where(
        person_group_memberships.c.person_id == person.id
    )
    res_groups = await db.execute(stmt_groups)
    group_ids = [row[0] for row in res_groups.fetchall() if row[0] is not None]

    return person, group_ids


async def _get_location_info(
    db: AsyncSession,
    *,
    device: Device,
) -> dict:
    """
    Retorna informações de localização sem lazy-load.
    Prioridade:
      1) floor_plan_id -> FloorPlan -> Floor -> Building
      2) floor_id -> Floor -> Building
      3) building_id -> Building
    """
    floor_plan_id = getattr(device, "floor_plan_id", None)
    floor_id = getattr(device, "floor_id", None)
    building_id = getattr(device, "building_id", None)

    if floor_plan_id:
        stmt = (
            select(
                FloorPlan.id,
                FloorPlan.name,
                Floor.id,
                Floor.name,
                Building.id,
                Building.name,
            )
            .select_from(FloorPlan)
            .outerjoin(Floor, FloorPlan.floor_id == Floor.id)
            .outerjoin(Building, Floor.building_id == Building.id)
            .where(FloorPlan.id == floor_plan_id)
        )
        res = await db.execute(stmt)
        row = res.first()

        if not row:
            return {
                "floor_plan_id": floor_plan_id,
                "floor_plan_name": None,
                "floor_id": None,
                "floor_name": None,
                "building_id": None,
                "building_name": None,
            }

        fp_id, fp_name, fl_id, fl_name, bld_id, bld_name = row
        return {
            "floor_plan_id": fp_id,
            "floor_plan_name": fp_name,
            "floor_id": fl_id,
            "floor_name": fl_name,
            "building_id": bld_id,
            "building_name": bld_name,
        }

    if floor_id:
        stmt = (
            select(
                Floor.id,
                Floor.name,
                Building.id,
                Building.name,
            )
            .select_from(Floor)
            .outerjoin(Building, Floor.building_id == Building.id)
            .where(Floor.id == floor_id)
        )
        res = await db.execute(stmt)
        row = res.first()
        if row:
            fl_id, fl_name, bld_id, bld_name = row
            return {
                "floor_plan_id": None,
                "floor_plan_name": None,
                "floor_id": fl_id,
                "floor_name": fl_name,
                "building_id": bld_id,
                "building_name": bld_name,
            }

    if building_id:
        stmt = select(Building.id, Building.name).where(Building.id == building_id)
        res = await db.execute(stmt)
        row = res.first()
        if row:
            bld_id, bld_name = row
            return {
                "floor_plan_id": None,
                "floor_plan_name": None,
                "floor_id": None,
                "floor_name": None,
                "building_id": bld_id,
                "building_name": bld_name,
            }

    return {
        "floor_plan_id": None,
        "floor_plan_name": None,
        "floor_id": None,
        "floor_name": None,
        "building_id": None,
        "building_name": None,
    }


async def _load_applicable_rules(
    db: AsyncSession,
    *,
    device_id: int,
    group_ids: List[int],
) -> List[AlertRule]:
    """
    Regras ativas para o device, filtradas por:
      - rule_type (FORBIDDEN_SECTOR, DWELL_TIME)
      - group_id IN grupos da pessoa OU group_id IS NULL (regra geral)
    """
    stmt = select(AlertRule).where(
        AlertRule.is_active.is_(True),
        AlertRule.device_id == device_id,
        AlertRule.rule_type.in_([FORBIDDEN_SECTOR, DWELL_TIME]),
    )

    if group_ids:
        stmt = stmt.where(
            or_(
                AlertRule.group_id.is_(None),
                AlertRule.group_id.in_(group_ids),
            )
        )
    else:
        stmt = stmt.where(AlertRule.group_id.is_(None))

    result = await db.execute(stmt)
    rules = list(result.scalars().all())

    logger.debug(
        "AlertEngine: found %s rules for device_id=%s group_ids=%s",
        len(rules),
        device_id,
        group_ids,
    )
    return rules


# ---------------------------------------------------------------------------
# Disparos RTLS (sessões)
# ---------------------------------------------------------------------------

async def _fire_forbidden_sector(
    db: AsyncSession,
    *,
    rule: AlertRule,
    device: Device,
    tag: Tag,
    person: Optional[Person],
    now: datetime,
    collection_log_id: int | None = None,
) -> None:
    """
    FORBIDDEN_SECTOR como sessão:

    - Entrada: cria AlertEvent (is_open=True)
    - Continua no mesmo gateway: atualiza last_seen_at e last_collection_log_id
    - Saída (apareceu em outro gateway/regra): fecha eventos abertos dessa TAG
      com ended_at = last_seen_at (última evidência dentro do setor)
    """
    now = _ensure_utc(now)

    # 1) Fecha quaisquer sessões FORBIDDEN_SECTOR abertas dessa TAG (em outros devices/regras)
    stmt_open = select(AlertEvent).where(
        AlertEvent.event_type == FORBIDDEN_SECTOR,
        AlertEvent.tag_id == tag.id,
        AlertEvent.is_open.is_(True),
    )
    res_open = await db.execute(stmt_open)
    open_events = res_open.scalars().all()

    for ev in open_events:
        if ev.device_id != device.id or ev.rule_id != rule.id:
            await _close_event_session(db, event=ev, reason="moved_to_other_device_or_rule")

    # 2) Procura sessão aberta para (regra, tag, device)
    stmt_existing = (
        select(AlertEvent)
        .where(
            AlertEvent.event_type == FORBIDDEN_SECTOR,
            AlertEvent.rule_id == rule.id,
            AlertEvent.tag_id == tag.id,
            AlertEvent.device_id == device.id,
            AlertEvent.is_open.is_(True),
        )
        .order_by(AlertEvent.started_at.desc())
        .limit(1)
    )
    res_existing = await db.execute(stmt_existing)
    existing = res_existing.scalar_one_or_none()

    if existing:
        # Atualiza "evidência" e last_seen_at
        payload = _safe_json_load(getattr(existing, "payload", None))
        payload.update(
            {
                "last_seen_at": now.isoformat(),
                "last_collection_log_id": collection_log_id,
            }
        )
        updated = await crud_alert_event.update(
            db,
            existing,
            {
                "last_seen_at": now,
                "last_collection_log_id": collection_log_id,
                "payload": _safe_json_dump(payload),
            },
        )
        # opcional: webhook a cada atualização (pode ser útil no front)
        try:
            await dispatch_webhooks(db, updated)
        except Exception:
            logger.exception("Failed to dispatch webhook on forbidden update (event_id=%s)", updated.id)
        return

    # 3) Não havia sessão -> cria evento (entrada)
    location = await _get_location_info(db, device=device)

    person_name = None
    if person is not None:
        person_name = getattr(person, "full_name", None) or getattr(person, "name", None)

    base_name = (
        person_name
        or getattr(tag, "code", None)
        or getattr(tag, "mac_address", None)
        or f"Tag {tag.id}"
    )

    device_label = (
        getattr(device, "name", None)
        or getattr(device, "mac_address", None)
        or f"Device {device.id}"
    )

    message = f"Entrada em setor proibido: {base_name} no gateway '{device_label}'."

    payload_dict = {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "event_type": FORBIDDEN_SECTOR,
        "device_id": device.id,
        "device_name": device_label,
        "tag_id": tag.id,
        "person_id": person.id if person else None,
        "person_full_name": person_name,
        "group_id": rule.group_id,
        "floor_plan_id": location["floor_plan_id"],
        "floor_plan_name": location["floor_plan_name"],
        "floor_id": location["floor_id"],
        "floor_name": location["floor_name"],
        "building_id": location["building_id"],
        "building_name": location["building_name"],
        "started_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "ended_at": None,
        "is_open": True,
        "message": message,
        "first_collection_log_id": collection_log_id,
        "last_collection_log_id": collection_log_id,
    }

    event_in = AlertEventCreate(
        rule_id=rule.id,
        event_type=FORBIDDEN_SECTOR,
        person_id=person.id if person else None,
        tag_id=tag.id,
        device_id=device.id,
        floor_plan_id=location["floor_plan_id"],
        floor_id=location["floor_id"],
        building_id=location["building_id"],
        group_id=rule.group_id,
        started_at=now,
        last_seen_at=now,
        ended_at=None,
        is_open=True,
        message=message,
        payload=_safe_json_dump(payload_dict),
        first_collection_log_id=collection_log_id,
        last_collection_log_id=collection_log_id,
    )

    new_event = await crud_alert_event.create(db, event_in)
    await dispatch_webhooks(db, new_event)


async def _fire_dwell_time(
    db: AsyncSession,
    *,
    rule: AlertRule,
    device: Device,
    tag: Tag,
    person: Optional[Person],
    now: datetime,
    collection_log_id: int | None = None,
) -> None:
    """
    DWELL_TIME como sessão:

    - Abre uma sessão por (regra, tag, device)
    - started_at = primeira evidência no device
    - last_seen_at atualizado por evidência
    - message passa a existir quando dwell_seconds >= max_dwell_seconds (se configurado)
    - Fecha sessões anteriores (DWELL_TIME) dessa TAG quando ela aparece em outro gateway/regra
      com ended_at = last_seen_at
    """
    now = _ensure_utc(now)

    # Fecha sessões DWELL_TIME abertas dessa TAG em outros devices/regras
    stmt_open = select(AlertEvent).where(
        AlertEvent.event_type == DWELL_TIME,
        AlertEvent.tag_id == tag.id,
        AlertEvent.is_open.is_(True),
    )
    res_open = await db.execute(stmt_open)
    open_events = res_open.scalars().all()

    for ev in open_events:
        if ev.device_id != device.id or ev.rule_id != rule.id:
            await _close_event_session(db, event=ev, reason="moved_to_other_device_or_rule")

    # Sessão atual (regra/tag/device)
    stmt = (
        select(AlertEvent)
        .where(
            AlertEvent.rule_id == rule.id,
            AlertEvent.event_type == DWELL_TIME,
            AlertEvent.tag_id == tag.id,
            AlertEvent.device_id == device.id,
            AlertEvent.is_open.is_(True),
        )
        .order_by(AlertEvent.started_at.asc())
        .limit(1)
    )
    result = await db.execute(stmt)
    event = result.scalars().first()

    if event is None:
        location = await _get_location_info(db, device=device)

        person_name = None
        if person is not None:
            person_name = getattr(person, "full_name", None) or getattr(person, "name", None)

        device_name = getattr(device, "name", None) or f"Device {device.id}"

        payload_dict = {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "event_type": DWELL_TIME,
            "device_id": device.id,
            "device_name": device_name,
            "tag_id": tag.id,
            "person_id": person.id if person else None,
            "person_full_name": person_name,
            "max_dwell_seconds": rule.max_dwell_seconds,
            "floor_plan_id": location["floor_plan_id"],
            "floor_plan_name": location["floor_plan_name"],
            "floor_id": location["floor_id"],
            "floor_name": location["floor_name"],
            "building_id": location["building_id"],
            "building_name": location["building_name"],
            "started_at": now.isoformat(),
            "last_seen_at": now.isoformat(),
            "is_open": True,
            "first_collection_log_id": collection_log_id,
            "last_collection_log_id": collection_log_id,
        }

        event_in = AlertEventCreate(
            rule_id=rule.id,
            event_type=DWELL_TIME,
            person_id=person.id if person else None,
            tag_id=tag.id,
            device_id=device.id,
            floor_plan_id=location["floor_plan_id"],
            floor_id=location["floor_id"],
            building_id=location["building_id"],
            group_id=rule.group_id,
            started_at=now,
            last_seen_at=now,
            ended_at=None,
            is_open=True,
            message=None,
            payload=_safe_json_dump(payload_dict),
            first_collection_log_id=collection_log_id,
            last_collection_log_id=collection_log_id,
        )

        created = await crud_alert_event.create(db, event_in)
        # webhook opcional no create
        try:
            await dispatch_webhooks(db, created)
        except Exception:
            logger.exception("Failed to dispatch webhook on dwell create (event_id=%s)", created.id)
        return

    started_at = _ensure_utc(getattr(event, "started_at", None))
    dwell_seconds = (now - started_at).total_seconds()

    location = await _get_location_info(db, device=device)

    person_name = None
    if person is not None:
        person_name = getattr(person, "full_name", None) or getattr(person, "name", None)

    base_name = (
        person_name
        or getattr(tag, "code", None)
        or getattr(tag, "mac_address", None)
        or f"Tag {tag.id}"
    )
    device_name = getattr(device, "name", None) or f"Device {device.id}"

    message: Optional[str] = None
    if rule.max_dwell_seconds is not None and dwell_seconds >= rule.max_dwell_seconds:
        message = (
            f"{base_name} está há {int(dwell_seconds)}s no dispositivo "
            f"{device_name} (limite {rule.max_dwell_seconds}s)."
        )

    payload_dict = _safe_json_load(getattr(event, "payload", None))
    payload_dict.update(
        {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "event_type": DWELL_TIME,
            "device_id": device.id,
            "device_name": device_name,
            "tag_id": tag.id,
            "person_id": person.id if person else None,
            "person_full_name": person_name,
            "max_dwell_seconds": rule.max_dwell_seconds,
            "dwell_seconds": dwell_seconds,
            "floor_plan_id": location["floor_plan_id"],
            "floor_plan_name": location["floor_plan_name"],
            "floor_id": location["floor_id"],
            "floor_name": location["floor_name"],
            "building_id": location["building_id"],
            "building_name": location["building_name"],
            "started_at": started_at.isoformat(),
            "last_seen_at": now.isoformat(),
            "message": message,
            "last_collection_log_id": collection_log_id,
        }
    )

    updated_event = await crud_alert_event.update(
        db,
        event,
        {
            "last_seen_at": now,
            "message": message,
            "payload": _safe_json_dump(payload_dict),
            "last_collection_log_id": collection_log_id,
        },
    )

    logger.info(
        "AlertEngine: DWELL_TIME update (rule_id=%s person_id=%s device_id=%s dwell=%.1fs)",
        rule.id,
        person.id if person else None,
        device.id,
        dwell_seconds,
    )

    # Você pode trocar a estratégia aqui se quiser:
    # - webhook só quando ultrapassar (se message não era None antes)
    # - ou sempre (como está)
    try:
        await dispatch_webhooks(db, updated_event)
    except Exception:
        logger.exception("Failed to dispatch webhook on dwell update (event_id=%s)", updated_event.id)


# ---------------------------------------------------------------------------
# Função principal - chamada pelo MQTT ingestor / collection_logs
# ---------------------------------------------------------------------------

async def process_detection(
    db: AsyncSession,
    device: Device,
    tag: Tag,
    *,
    collection_log_id: int | None = None,
    seen_at: datetime | None = None,
) -> None:
    """
    Chamado a cada detecção.

    Agora recebe:
      - collection_log_id: evidência do log que gerou a detecção
      - seen_at: timestamp do log (recomendado usar created_at do CollectionLog)

    Passos:
      1) Fecha sessões stale dessa TAG (Etapa 2, reentrada limpa)
      2) Carrega pessoa + grupos (sem lazy-load)
      3) Carrega regras aplicáveis
      4) Dispara FORBIDDEN_SECTOR / DWELL_TIME
    """
    now = _ensure_utc(seen_at)

    # ETAPA 2 (opportunistic): fecha sessões stale para esta TAG
    # Isso garante que, se a TAG "sumiu" e voltou, não reutilizamos sessão antiga.
    try:
        await close_stale_rtls_sessions(db, now=now, tag_id=tag.id)
    except Exception:
        logger.exception("Failed to close stale RTLS sessions for tag_id=%s", tag.id)

    person, group_ids = await _get_person_with_groups(db, tag=tag)

    rules = await _load_applicable_rules(
        db,
        device_id=device.id,
        group_ids=group_ids,
    )
    if not rules:
        return

    for rule in rules:
        if rule.rule_type == FORBIDDEN_SECTOR:
            await _fire_forbidden_sector(
                db=db,
                rule=rule,
                device=device,
                tag=tag,
                person=person,
                now=now,
                collection_log_id=collection_log_id,
            )
        elif rule.rule_type == DWELL_TIME:
            await _fire_dwell_time(
                db=db,
                rule=rule,
                device=device,
                tag=tag,
                person=person,
                now=now,
                collection_log_id=collection_log_id,
            )


# ---------------------------------------------------------------------------
# Eventos de status de gateway (OFFLINE / ONLINE) como SESSÃO
# (mantém coerência com relatórios: started_at / ended_at / duration)
# ---------------------------------------------------------------------------

async def handle_gateway_status_transition(
    db: AsyncSession,
    *,
    device: Device,
    is_online_now: bool,
) -> None:
    """
    Sessão de OFFLINE:

    - Se offline e não existe evento OFFLINE aberto: cria (is_open=True)
    - Se offline e já existe: atualiza last_seen_at + offline_seconds no payload
    - Se online e existe OFFLINE aberto: fecha (ended_at = last_seen_at da sessão OFFLINE)
      e cria um evento ONLINE pontual (is_open=False, ended_at=now)
    """
    now = datetime.now(timezone.utc)

    stmt = (
        select(AlertEvent)
        .where(
            AlertEvent.event_type == GATEWAY_OFFLINE,
            AlertEvent.device_id == device.id,
            AlertEvent.is_open.is_(True),
        )
        .order_by(AlertEvent.started_at.desc())
        .limit(1)
    )
    res = await db.execute(stmt)
    offline_event = res.scalar_one_or_none()

    location = await _get_location_info(db, device=device)

    device_label = (
        getattr(device, "name", None)
        or getattr(device, "mac_address", None)
        or f"Device {device.id}"
    )

    last_seen = getattr(device, "last_seen_at", None)
    last_seen = _ensure_utc(last_seen) if last_seen is not None else None
    offline_seconds_now = (now - last_seen).total_seconds() if last_seen else 0

    if not is_online_now:
        if offline_event is None:
            message = f"Gateway '{device_label}' ficou OFFLINE."

            payload_dict = {
                "event_type": GATEWAY_OFFLINE,
                "device_id": device.id,
                "device_name": device_label,
                "floor_plan_id": location["floor_plan_id"],
                "floor_plan_name": location["floor_plan_name"],
                "floor_id": location["floor_id"],
                "floor_name": location["floor_name"],
                "building_id": location["building_id"],
                "building_name": location["building_name"],
                "offline_started_at": now.isoformat(),
                "offline_seconds": offline_seconds_now,
                "is_open": True,
            }

            event_in = AlertEventCreate(
                rule_id=None,
                event_type=GATEWAY_OFFLINE,
                person_id=None,
                tag_id=None,
                device_id=device.id,
                floor_plan_id=location["floor_plan_id"],
                floor_id=location["floor_id"],
                building_id=location["building_id"],
                group_id=None,
                started_at=now,
                last_seen_at=now,
                ended_at=None,
                is_open=True,
                message=message,
                payload=_safe_json_dump(payload_dict),
            )
            event = await crud_alert_event.create(db, event_in)
            await dispatch_webhooks(db, event)
        else:
            payload_dict = _safe_json_load(getattr(offline_event, "payload", None))
            payload_dict["offline_seconds"] = offline_seconds_now
            payload_dict["last_seen_at"] = now.isoformat()

            updated_event = await crud_alert_event.update(
                db,
                offline_event,
                {
                    "last_seen_at": now,
                    "payload": _safe_json_dump(payload_dict),
                },
            )
            await dispatch_webhooks(db, updated_event)

        return

    # ONLINE
    if offline_event is None:
        return

    # fecha offline como sessão
    await _close_event_session(db, event=offline_event, reason="gateway_back_online")

    # cria evento ONLINE pontual
    message = f"Gateway '{device_label}' voltou a ficar ONLINE."
    online_payload = {
        "event_type": GATEWAY_ONLINE,
        "device_id": device.id,
        "device_name": device_label,
        "floor_plan_id": location["floor_plan_id"],
        "floor_plan_name": location["floor_plan_name"],
        "floor_id": location["floor_id"],
        "floor_name": location["floor_name"],
        "building_id": location["building_id"],
        "building_name": location["building_name"],
        "offline_seconds": offline_seconds_now,
        "is_open": False,
        "ended_at": now.isoformat(),
    }

    online_event_in = AlertEventCreate(
        rule_id=None,
        event_type=GATEWAY_ONLINE,
        person_id=None,
        tag_id=None,
        device_id=device.id,
        floor_plan_id=location["floor_plan_id"],
        floor_id=location["floor_id"],
        building_id=location["building_id"],
        group_id=None,
        started_at=now,
        last_seen_at=now,
        ended_at=now,
        is_open=False,
        message=message,
        payload=_safe_json_dump(online_payload),
    )
    online_event = await crud_alert_event.create(db, online_event_in)
    await dispatch_webhooks(db, online_event)


# wrappers usados pelo mqtt_ingestor (mantém compatibilidade)
async def fire_gateway_offline_event(
    db: AsyncSession,
    *,
    device: Device,
    now: datetime,
    offline_seconds: int,
) -> AlertEvent:
    # offline_seconds é derivável; mantemos compatibilidade com assinatura
    await handle_gateway_status_transition(db, device=device, is_online_now=False)
    # retorna o último evento OFFLINE aberto (best-effort)
    stmt = (
        select(AlertEvent)
        .where(
            AlertEvent.event_type == GATEWAY_OFFLINE,
            AlertEvent.device_id == device.id,
            AlertEvent.is_open.is_(True),
        )
        .order_by(AlertEvent.started_at.desc())
        .limit(1)
    )
    res = await db.execute(stmt)
    ev = res.scalar_one_or_none()
    return ev  # type: ignore[return-value]


async def fire_gateway_online_event(
    db: AsyncSession,
    *,
    device: Device,
    now: datetime,
) -> AlertEvent:
    await handle_gateway_status_transition(db, device=device, is_online_now=True)
    # retorna evento ONLINE mais recente
    stmt = (
        select(AlertEvent)
        .where(
            AlertEvent.event_type == GATEWAY_ONLINE,
            AlertEvent.device_id == device.id,
        )
        .order_by(AlertEvent.started_at.desc())
        .limit(1)
    )
    res = await db.execute(stmt)
    ev = res.scalar_one_or_none()
    return ev  # type: ignore[return-value]
