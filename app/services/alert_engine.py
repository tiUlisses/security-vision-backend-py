# app/services/alert_engine.py

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

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

logger = logging.getLogger("rtls.alert_engine")

FORBIDDEN_SECTOR = "FORBIDDEN_SECTOR"
DWELL_TIME = "DWELL_TIME"

GATEWAY_OFFLINE = "GATEWAY_OFFLINE"
GATEWAY_ONLINE = "GATEWAY_ONLINE"


# ---------------------------------------------------------------------------
# Helpers de consulta (SEM lazy loading)
# ---------------------------------------------------------------------------


async def _get_person_with_groups(
    db: AsyncSession,
    *,
    tag: Tag,
) -> Tuple[Optional[Person], List[int]]:
    """
    Carrega a pessoa associada à TAG (via tag.person_id) e
    os IDs dos grupos dessa pessoa.

    NUNCA usa tag.person ou person.groups (evita lazy-load e MissingGreenlet).
    """
    person_id = getattr(tag, "person_id", None)
    if not person_id:
        return None, []

    # 1) Carrega a pessoa explicitamente
    stmt_person = select(Person).where(Person.id == person_id)
    res_person = await db.execute(stmt_person)
    person = res_person.scalars().first()
    if not person:
        return None, []

    # 2) Carrega somente os IDs dos grupos via tabela de associação
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
    Retorna informações de localização a partir de device.floor_plan_id,
    SEM usar device.floor_plan (lazy).

    Retorna um dict com IDs e nomes de planta, andar e prédio.
    """
    floor_plan_id = getattr(device, "floor_plan_id", None)
    floor_id = getattr(device, "floor_id", None)
    building_id = getattr(device, "building_id", None)

    # 1) Se tiver planta, é a fonte de verdade (mantém comportamento antigo)
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

    # 2) Sem planta: usa building_id / floor_id vindos do MQTT (gateways)
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

    # 3) Sem info
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
    Carrega regras ativas para o device, filtrando por:
      - tipo (FORBIDDEN_SECTOR, DWELL_TIME)
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
        # Pessoa sem grupo -> só pega regras "gerais" (group_id = NULL)
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
# Disparos de eventos
# ---------------------------------------------------------------------------


async def _fire_forbidden_sector(
    db: AsyncSession,
    *,
    rule: AlertRule,
    device: Device,
    tag: Tag,
    person: Optional[Person],
    now: datetime,
) -> None:
    """
    FORBIDDEN_SECTOR como sessão:

    - Quando a pessoa entra em um gateway proibido:
        cria um AlertEvent com started_at = now, last_seen_at = now,
        ended_at = None, is_open = True.

    - Enquanto ela continuar nesse mesmo gateway proibido:
        não cria novo evento, apenas atualiza last_seen_at.

    - Quando ela aparecer em OUTRO gateway:
        fecha qualquer evento FORBIDDEN_SECTOR aberto dessa TAG
        (is_open = False, ended_at = now).
    """

    # Enriquecimento de localização (sem lazy load)
    location = await _get_location_info(db, device=device)

    # 1) Fecha eventos abertos FORBIDDEN_SECTOR dessa TAG em outros devices/regras
    stmt_open = (
        select(AlertEvent)
        .where(
            AlertEvent.event_type == FORBIDDEN_SECTOR,
            AlertEvent.tag_id == tag.id,
            AlertEvent.is_open.is_(True),
        )
    )
    res_open = await db.execute(stmt_open)
    open_events = res_open.scalars().all()

    for ev in open_events:
        # Se for outro device ou outra regra, consideramos que a sessão anterior acabou
        if ev.device_id != device.id or ev.rule_id != rule.id:
            await crud_alert_event.update(
                db,
                ev,
                {
                    "is_open": False,
                    "ended_at": now,
                    "last_seen_at": now,
                },
            )

    # 2) Verifica se já existe sessão aberta para (regra, tag, device)
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
        # Ainda está no mesmo setor proibido:
        # só atualiza last_seen_at (não cria novo evento)
        await crud_alert_event.update(
            db,
            existing,
            {"last_seen_at": now},
        )
        return

    # 3) Não havia sessão aberta -> entrada em área proibida
    if person is not None:
        person_name = getattr(person, "full_name", None) or getattr(
            person, "name", None
        )
    else:
        person_name = None

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

    # Payload JSON (livre, para debug / relatórios)
    # 🔹 AGORA COM CAMPOS PLANOS, ALINHADOS COM O FRONT E WEBHOOKS
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
    }

    # Usa Pydantic para garantir tipos corretos (datetime, bool, etc.)
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
        payload=json.dumps(payload_dict, ensure_ascii=False),
    )

    new_event = await crud_alert_event.create(db, event_in)

    # 🔔 dispara webhooks para FORBIDDEN_SECTOR
    await dispatch_webhooks(db, new_event)


async def _fire_dwell_time(
    db: AsyncSession,
    *,
    rule: AlertRule,
    device: Device,
    tag: Tag,
    person: Optional[Person],
    now: datetime,
) -> None:
    """
    Regra de permanência (DWELL_TIME):

    - Abre uma sessão de alerta por (regra, tag, device).
    - started_at = primeira vez que a TAG foi vista nesse contexto.
    - last_seen_at é atualizado a cada detecção.
    - message só é preenchida quando o tempo de permanência >= max_dwell_seconds.
    """

    # ------------------------------------------------------------------
    # 1) Procura se já existe uma sessão aberta DWELL_TIME
    #    (regra, tag, device, is_open = True)
    # ------------------------------------------------------------------
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
    )
    result = await db.execute(stmt)
    event = result.scalars().first()

    # ------------------------------------------------------------------
    # 2) Se NÃO existe sessão -> cria uma nova
    # ------------------------------------------------------------------
    if event is None:
        # Enriquecimento de localização na criação
        location = await _get_location_info(db, device=device)

        # Nome da pessoa / tag
        person_name = None
        if person is not None:
            person_name = getattr(person, "full_name", None) or getattr(
                person, "name", None
            )

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
            message=None,  # ainda não atingiu o limite
            payload=json.dumps(payload_dict, ensure_ascii=False),
        )

        await crud_alert_event.create(db, event_in)
        return

    # ------------------------------------------------------------------
    # 3) Se JÁ existe sessão -> atualiza last_seen + mensagem/payload
    # ------------------------------------------------------------------
    dwell_seconds = (now - event.started_at).total_seconds()

    # Enriquecimento de localização e nomes para o payload
    location = await _get_location_info(db, device=device)

    person_name = None
    if person is not None:
        person_name = getattr(person, "full_name", None) or getattr(
            person, "name", None
        )

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
        "dwell_seconds": dwell_seconds,
        "floor_plan_id": location["floor_plan_id"],
        "floor_plan_name": location["floor_plan_name"],
        "floor_id": location["floor_id"],
        "floor_name": location["floor_name"],
        "building_id": location["building_id"],
        "building_name": location["building_name"],
        "started_at": event.started_at.isoformat(),
        "last_seen_at": now.isoformat(),
        "message": message,
    }

    updated_event = await crud_alert_event.update(
        db,
        event,
        {
            "last_seen_at": now,
            "message": message,
            "payload": json.dumps(payload_dict, ensure_ascii=False),
        },
    )

    logger.info(
        "AlertEngine: DWELL_TIME fired (rule_id=%s person_id=%s device_id=%s dwell=%.1fs)",
        rule.id,
        person.id if person else None,
        device.id,
        dwell_seconds,
    )

    # Aqui você decide a estratégia:
    # - Se quiser webhook só quando ultrapassar o limite, cheque `if message is not None:`
    # - Se quiser sempre atualizar o front, manda sempre:
    await dispatch_webhooks(db, updated_event)


# ---------------------------------------------------------------------------
# Função principal - chamada pelo MQTT ingestor / collection_logs
# ---------------------------------------------------------------------------

async def handle_gateway_status_transition(
    db: AsyncSession,
    *,
    device: Device,
    is_online_now: bool,
) -> None:
    """
    Chamado, por exemplo, pelo endpoint /devices/status.

    - Se is_online_now=False e não existe evento GATEWAY_OFFLINE aberto:
        cria um AlertEvent GATEWAY_OFFLINE (is_open=True)
    - Se is_online_now=False e já existe evento OFFLINE aberto:
        atualiza last_seen_at + offline_seconds no payload
    - Se is_online_now=True e existe evento OFFLINE aberto:
        fecha esse evento e cria um evento GATEWAY_ONLINE
    """

    now = datetime.now(timezone.utc)

    # Evento OFFLINE aberto para este device?
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

    # Helper de localização (prédio/planta)
    async def _resolve_location() -> dict:
        return await _get_location_info(db, device=device)

    # Nome amigável do gateway
    device_label = (
        getattr(device, "name", None)
        or getattr(device, "mac_address", None)
        or f"Device {device.id}"
    )

    # Para calcular há quanto tempo está offline (com base no last_seen_at)
    last_seen = getattr(device, "last_seen_at", None)
    if last_seen is not None and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    offline_seconds_now = (
        (now - last_seen).total_seconds() if last_seen is not None else 0
    )

    # ------------------------------------------------------------------
    # Caso 1: gateway está OFFLINE agora
    # ------------------------------------------------------------------
    if not is_online_now:
        if offline_event is None:
            # Primeira vez que detectamos OFFLINE -> cria evento
            location = await _resolve_location()
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
                payload=json.dumps(payload_dict, ensure_ascii=False),
            )

            event = await crud_alert_event.create(db, event_in)
            await dispatch_webhooks(db, event)
        else:
            # Já estava OFFLINE -> só atualiza duração/last_seen_at
            try:
                payload_dict = (
                    json.loads(offline_event.payload)
                    if offline_event.payload
                    else {}
                )
            except json.JSONDecodeError:
                payload_dict = {}

            payload_dict["offline_seconds"] = offline_seconds_now

            updated_event = await crud_alert_event.update(
                db,
                offline_event,
                {
                    "last_seen_at": now,
                    "payload": json.dumps(payload_dict, ensure_ascii=False),
                },
            )
            await dispatch_webhooks(db, updated_event)

        return

    # ------------------------------------------------------------------
    # Caso 2: gateway está ONLINE agora
    # ------------------------------------------------------------------
    if offline_event is None:
        # Não havia sessão OFFLINE aberta -> nada a fazer
        return

    # Fecha a sessão OFFLINE e cria um evento ONLINE
    try:
        payload_dict = (
            json.loads(offline_event.payload) if offline_event.payload else {}
        )
    except json.JSONDecodeError:
        payload_dict = {}

    # Usa o offline_seconds calculado com base no last_seen_at
    payload_dict["offline_seconds"] = offline_seconds_now

    closed_event = await crud_alert_event.update(
        db,
        offline_event,
        {
            "is_open": False,
            "ended_at": now,
            "last_seen_at": now,
            "payload": json.dumps(payload_dict, ensure_ascii=False),
        },
    )
    await dispatch_webhooks(db, closed_event)

    # Cria um evento pontual de ONLINE
    location = await _resolve_location()
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
        payload=json.dumps(online_payload, ensure_ascii=False),
    )

    online_event = await crud_alert_event.create(db, online_event_in)
    await dispatch_webhooks(db, online_event)


async def process_detection(
    db: AsyncSession,
    device: Device,
    tag: Tag,
) -> None:
    """
    Chamado a cada detecção (via MQTT ou API).

    - Carrega pessoa + grupos SEM lazy-load
    - Carrega regras aplicáveis ao device + grupos da pessoa
    - Dispara FORBIDDEN_SECTOR e DWELL_TIME conforme necessário
    """
    now = datetime.now(timezone.utc)

    # Carrega pessoa + grupos uma vez (sem lazy) e reaproveita
    person, group_ids = await _get_person_with_groups(db, tag=tag)

    # Carrega regras ativas para o device filtrando por grupo
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
            )
        elif rule.rule_type == DWELL_TIME:
            await _fire_dwell_time(
                db=db,
                rule=rule,
                device=device,
                tag=tag,
                person=person,
                now=now,
            )


# ---------------------------------------------------------------------------
# Eventos de status de gateway (OFFLINE / ONLINE) - API p/ MQTT (se precisar)
# ---------------------------------------------------------------------------

async def _fire_gateway_status_event(
    db: AsyncSession,
    *,
    device: Device,
    now: datetime,
    event_type: str,
    offline_seconds: Optional[int] = None,
) -> AlertEvent:
    """
    Cria um AlertEvent simples para mudança de status de gateway.

    - event_type: GATEWAY_OFFLINE ou GATEWAY_ONLINE
    - rule_id, person_id, tag_id, group_id = None (evento sistêmico)
    """

    # Enriquecimento com localização (planta/andar/prédio)
    location = await _get_location_info(db, device=device)

    device_label = (
        getattr(device, "name", None)
        or getattr(device, "mac_address", None)
        or f"Device {device.id}"
    )

    if event_type == GATEWAY_OFFLINE:
        if offline_seconds is None:
            offline_seconds = 0
        message = (
            f"Gateway '{device_label}' OFFLINE "
            f"(sem publicações há {int(offline_seconds)}s)."
        )
    elif event_type == GATEWAY_ONLINE:
        message = f"Gateway '{device_label}' ONLINE novamente."
    else:
        raise ValueError(f"Unsupported gateway event_type: {event_type}")

    payload_dict = {
        "event_type": event_type,
        "device_id": device.id,
        "device_name": device_label,
        "device_mac_address": getattr(device, "mac_address", None),
        "floor_plan_id": location["floor_plan_id"],
        "floor_plan_name": location["floor_plan_name"],
        "floor_id": location["floor_id"],
        "floor_name": location["floor_name"],
        "building_id": location["building_id"],
        "building_name": location["building_name"],
        "offline_seconds": offline_seconds,
    }

    event_in = AlertEventCreate(
        rule_id=None,
        event_type=event_type,
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
        is_open=False,  # evento “instantâneo”
        message=message,
        payload=json.dumps(payload_dict, ensure_ascii=False),
    )

    created = await crud_alert_event.create(db, event_in)
    await dispatch_webhooks(db, created)
    return created


async def fire_gateway_offline_event(
    db: AsyncSession,
    *,
    device: Device,
    now: datetime,
    offline_seconds: int,
) -> AlertEvent:
    """
    API pública para o MQTT ingestor disparar evento de GATEWAY_OFFLINE.
    """
    return await _fire_gateway_status_event(
        db,
        device=device,
        now=now,
        event_type=GATEWAY_OFFLINE,
        offline_seconds=offline_seconds,
    )


async def fire_gateway_online_event(
    db: AsyncSession,
    *,
    device: Device,
    now: datetime,
) -> AlertEvent:
    """
    API pública para o MQTT ingestor disparar evento de GATEWAY_ONLINE.
    """
    return await _fire_gateway_status_event(
        db,
        device=device,
        now=now,
        event_type=GATEWAY_ONLINE,
    )
