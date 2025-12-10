# app/api/routes/reports.py
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Literal

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.alert_event import AlertEvent
from app.api.deps import get_db_session
from app.crud.presence_session import presence_session
from app.schemas.presence_session import PresenceSessionRead
from app.models.collection_log import CollectionLog
from app.models.presence_session import PresenceSession
from app.models.device import Device
from app.models.tag import Tag
from app.models.person import Person
from app.models.floor_plan import FloorPlan
from app.models.floor import Floor
from app.models.building import Building
from app.models.person_group import PersonGroup, person_group_memberships
from app.schemas.person_report import (
    PersonDwellByDevice,
    PersonPresenceSummary,
    PersonTimelineSession,
    PersonAlertByType,
    PersonAlertByDevice,
    PersonAlertEvent,
    PersonAlertsReport,
    PersonTimeDistributionBucket,
    PersonTimeDistributionCalendar,
    PersonTimeOfDayBucket,
    PersonTimeOfDayDistribution,
    PersonDayOfWeekBucket,
    PersonDayOfWeekDistribution,
    PersonGroupPresenceSummary,
    GroupDwellByDevice,
    GroupPersonDwellSummary,
    PersonGroupAlertsReport,
    PersonHourByGatewayBucket,
    PersonTimeOfDayByGateway,
)

from app.schemas.gateway_report import (
    GatewayUsageDeviceSummary,
    GatewayUsageSummary,
    GatewayTimeOfDayBucket,
    GatewayTimeOfDayDistribution,
)

router = APIRouter(tags=["reports"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build_group_sessions_subquery(
    group_id: int,
    *,
    from_ts: Optional[datetime],
    to_ts: Optional[datetime],
    min_duration_seconds: Optional[int],
):
    """
    Cria uma subquery de PresenceSession já filtrada para UM grupo,
    incluindo person_id e person_full_name para facilitar agregações.
    """
    from_ts_norm = _normalize_utc_naive(from_ts)
    to_ts_norm = _normalize_utc_naive(to_ts)

    base_stmt = (
        select(
            PresenceSession.id.label("id"),
            PresenceSession.device_id.label("device_id"),
            PresenceSession.tag_id.label("tag_id"),
            PresenceSession.started_at.label("started_at"),
            PresenceSession.ended_at.label("ended_at"),
            PresenceSession.duration_seconds.label("duration_seconds"),
            PresenceSession.samples_count.label("samples_count"),
            Person.id.label("person_id"),
            Person.full_name.label("person_full_name"),
        )
        .join(Tag, Tag.id == PresenceSession.tag_id)
        .join(Person, Person.id == Tag.person_id)
        .join(
            person_group_memberships,
            person_group_memberships.c.person_id == Person.id,
        )
        .where(person_group_memberships.c.group_id == group_id)
    )

    base_stmt = _apply_base_filters(
        base_stmt,
        from_ts=from_ts_norm,
        to_ts=to_ts_norm,
        device_id=None,
        tag_id=None,
        min_duration_seconds=min_duration_seconds,
    )

    return base_stmt.subquery("group_sessions")


@router.get(
    "/person-group/{group_id}/summary",
    response_model=PersonGroupPresenceSummary,
)
async def get_person_group_presence_summary(
    group_id: int,
    from_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra sessões a partir desta data/hora"
    ),
    to_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra sessões até esta data/hora"
    ),
    min_duration_seconds: Optional[int] = Query(
        default=None,
        description="Filtra sessões com duração mínima (segundos)"
    ),
    db: AsyncSession = Depends(get_db_session),
):
    # 1) Garante que o grupo existe
    group = await db.get(PersonGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Person group not found")

    # 2) Subquery de sessões do grupo
    sessions_subq = _build_group_sessions_subquery(
        group_id=group_id,
        from_ts=from_ts,
        to_ts=to_ts,
        min_duration_seconds=min_duration_seconds,
    )

    # 3) Agregação por device (gateway)
    by_device_stmt = (
        select(
            sessions_subq.c.device_id.label("device_id"),
            Device.name.label("device_name"),
            FloorPlan.id.label("floor_plan_id"),
            FloorPlan.name.label("floor_plan_name"),
            Floor.id.label("floor_id"),
            Floor.name.label("floor_name"),
            Building.id.label("building_id"),
            Building.name.label("building_name"),
            func.count().label("sessions_count"),
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds),
                0,
            ).label("total_dwell_seconds"),
            func.count(
                func.distinct(sessions_subq.c.person_id)
            ).label("unique_people_count"),
            func.min(sessions_subq.c.started_at).label("first_session_at"),
            func.max(sessions_subq.c.ended_at).label("last_session_at"),
        )
        .select_from(sessions_subq)
        .join(Device, Device.id == sessions_subq.c.device_id, isouter=True)
        .join(FloorPlan, FloorPlan.id == Device.floor_plan_id, isouter=True)
        .join(Floor, Floor.id == FloorPlan.floor_id, isouter=True)
        .join(Building, Building.id == Floor.building_id, isouter=True)
        .group_by(
            sessions_subq.c.device_id,
            Device.name,
            FloorPlan.id,
            FloorPlan.name,
            Floor.id,
            Floor.name,
            Building.id,
            Building.name,
        )
        .order_by(
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds), 0
            ).desc()
        )
    )

    res_dev = await db.execute(by_device_stmt)
    dev_rows = res_dev.all()

    dwell_by_device: List[GroupDwellByDevice] = []
    total_dwell_seconds = 0
    total_sessions = 0
    first_session_at = None
    last_session_at = None
    total_unique_people_set: set[int] = set()

    for row in dev_rows:
        td = int(row.total_dwell_seconds or 0)
        sc = int(row.sessions_count or 0)
        up = int(row.unique_people_count or 0)

        total_dwell_seconds += td
        total_sessions += sc

        if row.first_session_at and (
            first_session_at is None or row.first_session_at < first_session_at
        ):
            first_session_at = row.first_session_at
        if row.last_session_at and (
            last_session_at is None or row.last_session_at > last_session_at
        ):
            last_session_at = row.last_session_at

        dwell_by_device.append(
            GroupDwellByDevice(
                device_id=row.device_id,
                device_name=row.device_name,
                building_id=row.building_id,
                building_name=row.building_name,
                floor_id=row.floor_id,
                floor_name=row.floor_name,
                floor_plan_id=row.floor_plan_id,
                floor_plan_name=row.floor_plan_name,
                total_dwell_seconds=td,
                sessions_count=sc,
                unique_people_count=up,
            )
        )

    top_device_id = dwell_by_device[0].device_id if dwell_by_device else None

    # 4) Agregação por pessoa dentro do grupo
    by_person_stmt = (
        select(
            sessions_subq.c.person_id.label("person_id"),
            sessions_subq.c.person_full_name.label("person_full_name"),
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds),
                0,
            ).label("total_dwell_seconds"),
            func.count().label("sessions_count"),
        )
        .select_from(sessions_subq)
        .group_by(
            sessions_subq.c.person_id,
            sessions_subq.c.person_full_name,
        )
        .order_by(
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds),
                0,
            ).desc()
        )
    )

    res_person = await db.execute(by_person_stmt)
    person_rows = res_person.all()

    dwell_by_person: List[GroupPersonDwellSummary] = []

    for row in person_rows:
        td = int(row.total_dwell_seconds or 0)
        sc = int(row.sessions_count or 0)
        dwell_by_person.append(
            GroupPersonDwellSummary(
                person_id=row.person_id,
                person_full_name=row.person_full_name,
                total_dwell_seconds=td,
                sessions_count=sc,
            )
        )
        if row.person_id is not None:
            total_unique_people_set.add(row.person_id)

    total_unique_people = len(total_unique_people_set)

    from_norm = _normalize_utc_naive(from_ts)
    to_norm = _normalize_utc_naive(to_ts)

    return PersonGroupPresenceSummary(
        group_id=group.id,
        group_name=group.name,
        from_ts=from_norm,
        to_ts=to_norm,
        total_dwell_seconds=total_dwell_seconds,
        total_sessions=total_sessions,
        total_unique_people=total_unique_people,
        first_session_at=first_session_at,
        last_session_at=last_session_at,
        dwell_by_device=dwell_by_device,
        dwell_by_person=dwell_by_person,
        top_device_id=top_device_id,
    )

def _normalize_dt(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Converte datetime com tzinfo em datetime naive em UTC.

    - Se vier como 2025-11-21T00:00:00Z, o FastAPI cria um datetime
      com tzinfo=UTC. Precisamos remover o tzinfo para casar com
      TIMESTAMP WITHOUT TIME ZONE do Postgres.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)

def _build_gateway_sessions_subquery(
    *,
    from_ts: Optional[datetime],
    to_ts: Optional[datetime],
    min_duration_seconds: Optional[int],
    device_id: Optional[int] = None,
):
    """
    Subquery com sessões de presença (PresenceSession) para 1 ou N gateways.

    Não faz join com Person aqui; esse join é feito nos selects finais
    quando precisamos contar pessoas únicas.
    """
    from_ts_norm = _normalize_utc_naive(from_ts)
    to_ts_norm = _normalize_utc_naive(to_ts)

    base_stmt = select(
        PresenceSession.id.label("id"),
        PresenceSession.device_id.label("device_id"),
        PresenceSession.tag_id.label("tag_id"),
        PresenceSession.started_at.label("started_at"),
        PresenceSession.ended_at.label("ended_at"),
        PresenceSession.duration_seconds.label("duration_seconds"),
        PresenceSession.samples_count.label("samples_count"),
    )

    base_stmt = _apply_base_filters(
        base_stmt,
        from_ts=from_ts_norm,
        to_ts=to_ts_norm,
        device_id=device_id,
        tag_id=None,
        min_duration_seconds=min_duration_seconds,
    )

    return base_stmt.subquery("gateway_sessions")

def _build_person_sessions_subquery(
    person_id: int,
    *,
    from_ts: Optional[datetime],
    to_ts: Optional[datetime],
    min_duration_seconds: Optional[int],
):
    """
    Cria uma subquery de PresenceSession já filtrada para UMA pessoa,
    aplicando também o intervalo [from_ts, to_ts] e min_duration_seconds.
    """
    from_ts_norm = _normalize_utc_naive(from_ts)
    to_ts_norm = _normalize_utc_naive(to_ts)

    base_stmt = (
        select(
            PresenceSession.id.label("id"),
            PresenceSession.device_id.label("device_id"),
            PresenceSession.tag_id.label("tag_id"),
            PresenceSession.started_at.label("started_at"),
            PresenceSession.ended_at.label("ended_at"),
            PresenceSession.duration_seconds.label("duration_seconds"),
            PresenceSession.samples_count.label("samples_count"),
        )
        .join(Tag, Tag.id == PresenceSession.tag_id)
        .where(Tag.person_id == person_id)
    )

    base_stmt = _apply_base_filters(
        base_stmt,
        from_ts=from_ts_norm,
        to_ts=to_ts_norm,
        device_id=None,
        tag_id=None,
        min_duration_seconds=min_duration_seconds,
    )

    return base_stmt.subquery("person_sessions")

def _normalize_utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Converte qualquer datetime (com ou sem tzinfo) para UTC "naive"
    (sem tzinfo), pra evitar o erro:
    "can't subtract offset-naive and offset-aware datetimes"
    com o asyncpg/postgres.
    """
    if dt is None:
        return None

    # já é naive -> devolve como está
    if dt.tzinfo is None:
        return dt

    # converte pra UTC e remove tzinfo
    return dt.astimezone(timezone.utc).replace(tzinfo=None)



def _apply_base_filters(
    stmt,
    *,
    from_ts: Optional[datetime],
    to_ts: Optional[datetime],
    device_id: Optional[int],
    tag_id: Optional[int],
    min_duration_seconds: Optional[int] = None,
):
    """
    Aplica filtros base em PresenceSession usando lógica de INTERSEÇÃO de intervalos.

    Regra: sessão [started_at, ended_at] INTERSECTA a janela [from_ts, to_ts].

    - Se ambos from_ts e to_ts forem informados:
        started_at <= to_ts
        AND (ended_at >= from_ts OR ended_at IS NULL)

    - Se só from_ts:
        (ended_at >= from_ts OR ended_at IS NULL)

    - Se só to_ts:
        started_at <= to_ts

    Além disso aplica device_id, tag_id e min_duration_seconds se existirem.
    """

    if from_ts is not None and to_ts is not None:
        stmt = stmt.where(
            PresenceSession.started_at <= to_ts,
            or_(
                PresenceSession.ended_at.is_(None),
                PresenceSession.ended_at >= from_ts,
            ),
        )
    elif from_ts is not None:
        stmt = stmt.where(
            or_(
                PresenceSession.ended_at.is_(None),
                PresenceSession.ended_at >= from_ts,
            )
        )
    elif to_ts is not None:
        stmt = stmt.where(PresenceSession.started_at <= to_ts)

    if device_id is not None:
        stmt = stmt.where(PresenceSession.device_id == device_id)
    if tag_id is not None:
        stmt = stmt.where(PresenceSession.tag_id == tag_id)

    if min_duration_seconds is not None:
        stmt = stmt.where(PresenceSession.duration_seconds >= min_duration_seconds)

    return stmt


# ---------------------------------------------------------------------------
# Endpoint: lista sessões de presença (dwell sessions)
# ---------------------------------------------------------------------------

@router.get(
    "/dwell-sessions",
    response_model=List[PresenceSessionRead],
)
async def list_dwell_sessions(
    skip: int = 0,
    limit: int = 100,
    device_id: int | None = Query(default=None),
    tag_id: int | None = Query(default=None),
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Lista sessões de presença (agrupadas a partir de collection_logs).

    Pode filtrar por device, tag e intervalo de datas para usar
    na tela de relatórios de tempo de permanência.
    """

    # normaliza para naive
    norm_from = _normalize_dt(from_ts)
    norm_to = _normalize_dt(to_ts)

    sessions = await presence_session.get_multi(
        db,
        skip=skip,
        limit=limit,
        device_id=device_id,
        tag_id=tag_id,
        from_ts=norm_from,
        to_ts=norm_to,
    )
    return sessions


# ---------------------------------------------------------------------------
# Overview de relatórios para dashboards
# ---------------------------------------------------------------------------

@router.get("/overview", response_model=dict)
async def reports_overview(
    from_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra coletas a partir desta data/hora (created_at >= from_ts)",
    ),
    to_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra coletas até esta data/hora (created_at <= to_ts)",
    ),
    device_id: int | None = Query(
        default=None,
        description="Opcional: filtra por device específico",
    ),
    tag_id: int | None = Query(
        default=None,
        description="Opcional: filtra por TAG específica",
    ),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Overview de relatórios para dashboards.

    Aqui não usamos mais a tabela/VIEW presence_sessions.
    Em vez disso, agregamos diretamente de collection_logs:

    - Agrupando por (device_id, tag_id)
    - Calculando started_at, ended_at, duration_seconds
    """

    # -------------------------------------------------------------------
    # 0) Normaliza datas para UTC naive (evita erro de offset naive/aware)
    # -------------------------------------------------------------------
    from_norm = _normalize_utc_naive(from_ts)
    to_norm = _normalize_utc_naive(to_ts)

    # -------------------------------------------------------------------
    # 1) Base: coletas filtradas (collection_logs)
    # -------------------------------------------------------------------
    base_logs_stmt = (
        select(
            CollectionLog.device_id.label("device_id"),
            CollectionLog.tag_id.label("tag_id"),
            CollectionLog.created_at.label("created_at"),
        )
        .where(
            CollectionLog.device_id.is_not(None),
            CollectionLog.tag_id.is_not(None),
        )
    )

    if from_norm is not None:
        base_logs_stmt = base_logs_stmt.where(
            CollectionLog.created_at >= from_norm
        )
    if to_norm is not None:
        base_logs_stmt = base_logs_stmt.where(
            CollectionLog.created_at <= to_norm
        )
    if device_id is not None:
        base_logs_stmt = base_logs_stmt.where(
            CollectionLog.device_id == device_id
        )
    if tag_id is not None:
        base_logs_stmt = base_logs_stmt.where(
            CollectionLog.tag_id == tag_id
        )

    logs_subq = base_logs_stmt.subquery("logs")

    # -------------------------------------------------------------------
    # 2) "Sessões" agregadas por (device_id, tag_id)
    # -------------------------------------------------------------------
    sessions_subq = (
        select(
            logs_subq.c.device_id.label("device_id"),
            logs_subq.c.tag_id.label("tag_id"),
            func.min(logs_subq.c.created_at).label("started_at"),
            func.max(logs_subq.c.created_at).label("ended_at"),
            # duração em segundos entre primeira e última coleta
            func.extract(
                "epoch",
                func.max(logs_subq.c.created_at) - func.min(logs_subq.c.created_at),
            ).label("duration_seconds"),
        )
        .group_by(
            logs_subq.c.device_id,
            logs_subq.c.tag_id,
        )
    ).subquery("sessions")

    # -------------------------------------------------------------------
    # 3) SUMMARY GLOBAL
    # -------------------------------------------------------------------
    summary_stmt = select(
        func.count().label("total_sessions"),
        func.count(func.distinct(sessions_subq.c.tag_id)).label(
            "total_unique_tags"
        ),
        func.count(func.distinct(sessions_subq.c.device_id)).label(
            "total_unique_devices"
        ),
        func.coalesce(
            func.sum(sessions_subq.c.duration_seconds), 0
        ).label("total_dwell_seconds"),
        func.avg(sessions_subq.c.duration_seconds).label("avg_dwell_seconds"),
        func.min(sessions_subq.c.started_at).label("first_session_at"),
        func.max(sessions_subq.c.ended_at).label("last_session_at"),
    ).select_from(sessions_subq)

    summary_res = await db.execute(summary_stmt)
    summary_row = summary_res.one()

    summary = {
        "from_ts": from_ts,
        "to_ts": to_ts,
        "total_sessions": int(summary_row.total_sessions or 0),
        "total_unique_tags": int(summary_row.total_unique_tags or 0),
        "total_unique_devices": int(summary_row.total_unique_devices or 0),
        "total_dwell_seconds": int(summary_row.total_dwell_seconds or 0),
        "avg_dwell_seconds": float(summary_row.avg_dwell_seconds or 0.0)
        if summary_row.avg_dwell_seconds is not None
        else 0.0,
        "first_session_at": summary_row.first_session_at,
        "last_session_at": summary_row.last_session_at,
    }

    # -------------------------------------------------------------------
    # 4) TOP BUILDINGS (por dwell total)
    # -------------------------------------------------------------------
    top_buildings_stmt = (
        select(
            Building.id.label("building_id"),
            Building.name.label("building_name"),
            func.count().label("total_sessions"),
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds), 0
            ).label("total_dwell_seconds"),
        )
        .select_from(sessions_subq)
        .join(Device, Device.id == sessions_subq.c.device_id, isouter=True)
        .join(FloorPlan, FloorPlan.id == Device.floor_plan_id, isouter=True)
        .join(Floor, Floor.id == FloorPlan.floor_id, isouter=True)
        .join(Building, Building.id == Floor.building_id, isouter=True)
        .group_by(Building.id, Building.name)
        .order_by(
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds), 0
            ).desc()
        )
        .limit(10)
    )

    tb_res = await db.execute(top_buildings_stmt)
    top_buildings: List[Dict[str, Any]] = []
    for row in tb_res.all():
        if row.building_id is None and row.total_sessions == 0:
            continue
        top_buildings.append(
            {
                "building_id": row.building_id,
                "building_name": row.building_name or "Sem prédio",
                "total_sessions": int(row.total_sessions or 0),
                "total_dwell_seconds": int(row.total_dwell_seconds or 0),
            }
        )

    # -------------------------------------------------------------------
    # 5) TOP FLOORS (por dwell total)
    # -------------------------------------------------------------------
    top_floors_stmt = (
        select(
            Building.id.label("building_id"),
            Building.name.label("building_name"),
            Floor.id.label("floor_id"),
            Floor.name.label("floor_name"),
            func.count().label("total_sessions"),
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds), 0
            ).label("total_dwell_seconds"),
        )
        .select_from(sessions_subq)
        .join(Device, Device.id == sessions_subq.c.device_id, isouter=True)
        .join(FloorPlan, FloorPlan.id == Device.floor_plan_id, isouter=True)
        .join(Floor, Floor.id == FloorPlan.floor_id, isouter=True)
        .join(Building, Building.id == Floor.building_id, isouter=True)
        .group_by(
            Building.id,
            Building.name,
            Floor.id,
            Floor.name,
        )
        .order_by(
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds), 0
            ).desc()
        )
        .limit(10)
    )

    tf_res = await db.execute(top_floors_stmt)
    top_floors: List[Dict[str, Any]] = []
    for row in tf_res.all():
        if row.floor_id is None:
            continue
        top_floors.append(
            {
                "building_id": row.building_id,
                "building_name": row.building_name or "Sem prédio",
                "floor_id": row.floor_id,
                "floor_name": row.floor_name or "Sem andar",
                "total_sessions": int(row.total_sessions or 0),
                "total_dwell_seconds": int(row.total_dwell_seconds or 0),
            }
        )

    # -------------------------------------------------------------------
    # 6) TOP DEVICES (por dwell total)
    # -------------------------------------------------------------------
    top_devices_stmt = (
        select(
            sessions_subq.c.device_id.label("device_id"),
            Device.name.label("device_name"),
            func.count().label("total_sessions"),
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds), 0
            ).label("total_dwell_seconds"),
        )
        .select_from(sessions_subq)
        .join(Device, Device.id == sessions_subq.c.device_id, isouter=False)
        .group_by(sessions_subq.c.device_id, Device.name)
        .order_by(
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds), 0
            ).desc()
        )
        .limit(10)
    )

    td_res = await db.execute(top_devices_stmt)
    top_devices: List[Dict[str, Any]] = []
    for row in td_res.all():
        top_devices.append(
            {
                "device_id": row.device_id,
                "device_name": row.device_name
                or f"Device {row.device_id}",
                "total_sessions": int(row.total_sessions or 0),
                "total_dwell_seconds": int(row.total_dwell_seconds or 0),
            }
        )

    # -------------------------------------------------------------------
    # 7) TOP PEOPLE (por dwell total)
    # -------------------------------------------------------------------
    top_people_stmt = (
        select(
            Person.id.label("person_id"),
            Person.full_name.label("person_name"),
            func.count().label("total_sessions"),
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds), 0
            ).label("total_dwell_seconds"),
        )
        .select_from(sessions_subq)
        .join(Tag, Tag.id == sessions_subq.c.tag_id, isouter=True)
        .join(Person, Person.id == Tag.person_id, isouter=True)
        .where(Person.id.is_not(None))
        .group_by(Person.id, Person.full_name)
        .order_by(
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds), 0
            ).desc()
        )
        .limit(10)
    )

    tpe_res = await db.execute(top_people_stmt)
    top_people: List[Dict[str, Any]] = []
    for row in tpe_res.all():
        top_people.append(
            {
                "person_id": row.person_id,
                "person_name": row.person_name
                or f"Pessoa {row.person_id}",
                "total_sessions": int(row.total_sessions or 0),
                "total_dwell_seconds": int(row.total_dwell_seconds or 0),
            }
        )

    # -------------------------------------------------------------------
    # 8) TOP GROUPS (por dwell total)
    # -------------------------------------------------------------------
    top_groups_stmt = (
        select(
            PersonGroup.id.label("group_id"),
            PersonGroup.name.label("group_name"),
            func.count().label("total_sessions"),
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds), 0
            ).label("total_dwell_seconds"),
        )
        .select_from(sessions_subq)
        .join(Tag, Tag.id == sessions_subq.c.tag_id, isouter=True)
        .join(Person, Person.id == Tag.person_id, isouter=True)
        .join(
            person_group_memberships,
            person_group_memberships.c.person_id == Person.id,
            isouter=True,
        )
        .join(
            PersonGroup,
            PersonGroup.id == person_group_memberships.c.group_id,
            isouter=True,
        )
        .where(PersonGroup.id.is_not(None))
        .group_by(PersonGroup.id, PersonGroup.name)
        .order_by(
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds), 0
            ).desc()
        )
        .limit(10)
    )

    tg_res = await db.execute(top_groups_stmt)
    top_groups: List[Dict[str, Any]] = []
    for row in tg_res.all():
        top_groups.append(
            {
                "group_id": row.group_id,
                "group_name": row.group_name
                or f"Grupo {row.group_id}",
                "total_sessions": int(row.total_sessions or 0),
                "total_dwell_seconds": int(row.total_dwell_seconds or 0),
            }
        )

    # -------------------------------------------------------------------
    # 9) RESPOSTA FINAL
    # -------------------------------------------------------------------
    return {
        "summary": summary,
        "top_buildings": top_buildings,
        "top_floors": top_floors,
        "top_devices": top_devices,
        "top_people": top_people,
        "top_groups": top_groups,
    }


@router.get(
    "/person/{person_id}/alerts",
    response_model=PersonAlertsReport,
)
async def get_person_alerts_report(
    person_id: int,
    from_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra alertas a partir desta data/hora (campo started_at)",
    ),
    to_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra alertas até esta data/hora (campo started_at)",
    ),
    event_type: Optional[str] = Query(
        default=None,
        description="Filtra por tipo de alerta (event_type)",
    ),
    device_id: Optional[int] = Query(
        default=None,
        description="Filtra por device/gateway específico",
    ),
    max_events: int = Query(
        default=1000,
        ge=1,
        le=10000,
        description="Limite máximo de eventos retornados na lista",
    ),
    db: AsyncSession = Depends(get_db_session),
):
    # 1) Garante que a pessoa existe
    person = await db.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    from_norm = _normalize_utc_naive(from_ts)
    to_norm = _normalize_utc_naive(to_ts)

    # 2) Monta filtros base
    filters = [AlertEvent.person_id == person_id]

    if from_norm is not None:
        filters.append(AlertEvent.started_at >= from_norm)
    if to_norm is not None:
        filters.append(AlertEvent.started_at <= to_norm)
    if event_type is not None:
        filters.append(AlertEvent.event_type == event_type)
    if device_id is not None:
        filters.append(AlertEvent.device_id == device_id)

    # 3) Query principal de eventos com contexto de localização
    events_stmt = (
        select(
            AlertEvent.id.label("id"),
            AlertEvent.event_type.label("event_type"),
            AlertEvent.device_id.label("device_id"),
            AlertEvent.tag_id.label("tag_id"),
            AlertEvent.started_at.label("started_at"),
            AlertEvent.ended_at.label("ended_at"),
            Device.name.label("device_name"),
            FloorPlan.id.label("floor_plan_id"),
            FloorPlan.name.label("floor_plan_name"),
            Floor.id.label("floor_id"),
            Floor.name.label("floor_name"),
            Building.id.label("building_id"),
            Building.name.label("building_name"),
        )
        .select_from(AlertEvent)
        .join(Device, Device.id == AlertEvent.device_id, isouter=True)
        .join(FloorPlan, FloorPlan.id == Device.floor_plan_id, isouter=True)
        .join(Floor, Floor.id == FloorPlan.floor_id, isouter=True)
        .join(Building, Building.id == Floor.building_id, isouter=True)
        .where(*filters)
        .order_by(AlertEvent.started_at.desc())
        .limit(max_events)
    )

    result = await db.execute(events_stmt)
    rows = result.all()

    # 4) Agregações em memória
    total_alerts = 0
    first_alert_at: Optional[datetime] = None
    last_alert_at: Optional[datetime] = None

    by_type_map: dict[str, int] = {}
    by_device_map: dict[Optional[int], dict[str, Any]] = {}

    events: List[PersonAlertEvent] = []

    for row in rows:
        total_alerts += 1
        started_at = row.started_at

        # resumo temporal
        if started_at:
            if first_alert_at is None or started_at < first_alert_at:
                first_alert_at = started_at
            if last_alert_at is None or started_at > last_alert_at:
                last_alert_at = started_at

        # por tipo
        et = row.event_type or "UNKNOWN"
        by_type_map[et] = by_type_map.get(et, 0) + 1

        # por device
        dev_key = row.device_id
        if dev_key not in by_device_map:
            by_device_map[dev_key] = {
                "device_id": row.device_id,
                "device_name": row.device_name,
                "building_id": row.building_id,
                "building_name": row.building_name,
                "floor_id": row.floor_id,
                "floor_name": row.floor_name,
                "alerts_count": 0,
            }
        by_device_map[dev_key]["alerts_count"] += 1

        # item da lista de eventos
        events.append(
            PersonAlertEvent(
                id=row.id,
                event_type=row.event_type,
                device_id=row.device_id,
                device_name=row.device_name,
                building_id=row.building_id,
                building_name=row.building_name,
                floor_id=row.floor_id,
                floor_name=row.floor_name,
                floor_plan_id=row.floor_plan_id,
                floor_plan_name=row.floor_plan_name,
                tag_id=row.tag_id,
                started_at=row.started_at,
                ended_at=row.ended_at,
            )
        )

    # 5) Converte agregados para listas ordenadas
    by_type = [
        PersonAlertByType(event_type=et, alerts_count=count)
        for et, count in by_type_map.items()
    ]
    by_type.sort(key=lambda x: x.alerts_count, reverse=True)

    by_device = [
        PersonAlertByDevice(**data)
        for data in by_device_map.values()
    ]
    by_device.sort(key=lambda x: x.alerts_count, reverse=True)

    return PersonAlertsReport(
        person_id=person.id,
        person_full_name=person.full_name,
        from_ts=from_norm,
        to_ts=to_norm,
        total_alerts=total_alerts,
        first_alert_at=first_alert_at,
        last_alert_at=last_alert_at,
        by_type=by_type,
        by_device=by_device,
        events=events,
    )

@router.get(
    "/person/{person_id}/time-distribution/calendar",
    response_model=PersonTimeDistributionCalendar,
)
async def get_person_time_distribution_calendar(
    person_id: int,
    granularity: Literal["day", "week", "month", "year"] = Query(
        default="day",
        description="Granularidade do bucket: day, week, month ou year",
    ),
    from_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra sessões a partir desta data/hora",
    ),
    to_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra sessões até esta data/hora",
    ),
    min_duration_seconds: Optional[int] = Query(
        default=None,
        description="Filtra sessões com duração mínima (segundos)",
    ),
    db: AsyncSession = Depends(get_db_session),
):
    # 1) Garante que a pessoa existe
    person = await db.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    # 2) Subquery de sessões da pessoa
    sessions_subq = _build_person_sessions_subquery(
        person_id=person_id,
        from_ts=from_ts,
        to_ts=to_ts,
        min_duration_seconds=min_duration_seconds,
    )

    # 3) Define expressão de bucket (date_trunc no Postgres)
    bucket_expr = func.date_trunc(
        granularity,
        sessions_subq.c.started_at,
    ).label("bucket_start")

    stmt = (
        select(
            bucket_expr,
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds),
                0,
            ).label("total_dwell_seconds"),
            func.count().label("sessions_count"),
        )
        .select_from(sessions_subq)
        .group_by(bucket_expr)
        .order_by(bucket_expr)
    )

    res = await db.execute(stmt)
    rows = res.all()

    buckets: List[PersonTimeDistributionBucket] = []
    for row in rows:
        buckets.append(
            PersonTimeDistributionBucket(
                bucket_start=row.bucket_start,
                total_dwell_seconds=int(row.total_dwell_seconds or 0),
                sessions_count=int(row.sessions_count or 0),
            )
        )

    from_norm = _normalize_utc_naive(from_ts)
    to_norm = _normalize_utc_naive(to_ts)

    return PersonTimeDistributionCalendar(
        person_id=person.id,
        person_full_name=person.full_name,
        from_ts=from_norm,
        to_ts=to_norm,
        granularity=granularity,
        buckets=buckets,
    )


@router.get(
    "/person/{person_id}/time-distribution/hour-of-day",
    response_model=PersonTimeOfDayDistribution,
)
async def get_person_time_distribution_hour_of_day(
    person_id: int,
    from_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra sessões a partir desta data/hora",
    ),
    to_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra sessões até esta data/hora",
    ),
    min_duration_seconds: Optional[int] = Query(
        default=None,
        description="Filtra sessões com duração mínima (segundos)",
    ),
    db: AsyncSession = Depends(get_db_session),
):
    person = await db.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    sessions_subq = _build_person_sessions_subquery(
        person_id=person_id,
        from_ts=from_ts,
        to_ts=to_ts,
        min_duration_seconds=min_duration_seconds,
    )

    hour_expr = func.extract(
        "hour",
        sessions_subq.c.started_at,
    ).label("hour")

    stmt = (
        select(
            hour_expr,
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds),
                0,
            ).label("total_dwell_seconds"),
            func.count().label("sessions_count"),
        )
        .select_from(sessions_subq)
        .group_by(hour_expr)
        .order_by(hour_expr)
    )

    res = await db.execute(stmt)
    rows = res.all()

    buckets: List[PersonTimeOfDayBucket] = []
    for row in rows:
        # extract retorna float, convertemos pra int
        hour_int = int(row.hour)
        buckets.append(
            PersonTimeOfDayBucket(
                hour=hour_int,
                total_dwell_seconds=int(row.total_dwell_seconds or 0),
                sessions_count=int(row.sessions_count or 0),
            )
        )

    from_norm = _normalize_utc_naive(from_ts)
    to_norm = _normalize_utc_naive(to_ts)

    return PersonTimeOfDayDistribution(
        person_id=person.id,
        person_full_name=person.full_name,
        from_ts=from_norm,
        to_ts=to_norm,
        buckets=buckets,
    )


@router.get(
    "/person/{person_id}/time-distribution/day-of-week",
    response_model=PersonDayOfWeekDistribution,
)
async def get_person_time_distribution_day_of_week(
    person_id: int,
    from_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra sessões a partir desta data/hora",
    ),
    to_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra sessões até esta data/hora",
    ),
    min_duration_seconds: Optional[int] = Query(
        default=None,
        description="Filtra sessões com duração mínima (segundos)",
    ),
    db: AsyncSession = Depends(get_db_session),
):
    person = await db.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    sessions_subq = _build_person_sessions_subquery(
        person_id=person_id,
        from_ts=from_ts,
        to_ts=to_ts,
        min_duration_seconds=min_duration_seconds,
    )

    dow_expr = func.extract(
        "dow",
        sessions_subq.c.started_at,
    ).label("dow")  # 0=domingo, 1=segunda, ..., 6=sábado

    stmt = (
        select(
            dow_expr,
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds),
                0,
            ).label("total_dwell_seconds"),
            func.count().label("sessions_count"),
        )
        .select_from(sessions_subq)
        .group_by(dow_expr)
        .order_by(dow_expr)
    )

    res = await db.execute(stmt)
    rows = res.all()

    buckets: List[PersonDayOfWeekBucket] = []
    for row in rows:
        dow_int = int(row.dow)
        buckets.append(
            PersonDayOfWeekBucket(
                day_of_week=dow_int,
                total_dwell_seconds=int(row.total_dwell_seconds or 0),
                sessions_count=int(row.sessions_count or 0),
            )
        )

    from_norm = _normalize_utc_naive(from_ts)
    to_norm = _normalize_utc_naive(to_ts)

    return PersonDayOfWeekDistribution(
        person_id=person.id,
        person_full_name=person.full_name,
        from_ts=from_norm,
        to_ts=to_norm,
        buckets=buckets,
    )

@router.get(
    "/gateways/usage-summary",
    response_model=GatewayUsageSummary,
)
async def get_gateway_usage_summary(
    from_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra sessões a partir desta data/hora",
    ),
    to_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra sessões até esta data/hora",
    ),
    building_id: Optional[int] = Query(
        default=None,
        description="Filtra por prédio específico",
    ),
    floor_id: Optional[int] = Query(
        default=None,
        description="Filtra por andar específico",
    ),
    floor_plan_id: Optional[int] = Query(
        default=None,
        description="Filtra por planta específica",
    ),
    device_id: Optional[int] = Query(
        default=None,
        description="Filtra por um gateway específico",
    ),
    min_duration_seconds: Optional[int] = Query(
        default=None,
        description="Filtra sessões com duração mínima (segundos)",
    ),
    db: AsyncSession = Depends(get_db_session),
):
    # 1) Subquery base de sessões
    sessions_subq = _build_gateway_sessions_subquery(
        from_ts=from_ts,
        to_ts=to_ts,
        min_duration_seconds=min_duration_seconds,
        device_id=device_id,
    )

    # 2) Agregação por device, com contexto e pessoas únicas
    stmt = (
        select(
            sessions_subq.c.device_id.label("device_id"),
            Device.name.label("device_name"),
            Device.mac_address.label("device_mac_address"),  # ajuste se o nome do campo for diferente
            FloorPlan.id.label("floor_plan_id"),
            FloorPlan.name.label("floor_plan_name"),
            Floor.id.label("floor_id"),
            Floor.name.label("floor_name"),
            Building.id.label("building_id"),
            Building.name.label("building_name"),
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds),
                0,
            ).label("total_dwell_seconds"),
            func.count().label("sessions_count"),
            func.count(
                func.distinct(Person.id)
            ).label("unique_people_count"),
            func.min(sessions_subq.c.started_at).label("first_session_at"),
            func.max(sessions_subq.c.ended_at).label("last_session_at"),
        )
        .select_from(sessions_subq)
        .join(Device, Device.id == sessions_subq.c.device_id, isouter=True)
        .join(FloorPlan, FloorPlan.id == Device.floor_plan_id, isouter=True)
        .join(Floor, Floor.id == FloorPlan.floor_id, isouter=True)
        .join(Building, Building.id == Floor.building_id, isouter=True)
        .join(Tag, Tag.id == sessions_subq.c.tag_id, isouter=True)
        .join(Person, Person.id == Tag.person_id, isouter=True)
    )

    # 3) Filtros espaciais (prédio/andar/planta)
    if building_id is not None:
        stmt = stmt.where(Building.id == building_id)
    if floor_id is not None:
        stmt = stmt.where(Floor.id == floor_id)
    if floor_plan_id is not None:
        stmt = stmt.where(FloorPlan.id == floor_plan_id)

    stmt = stmt.group_by(
        sessions_subq.c.device_id,
        Device.name,
        Device.mac_address,
        FloorPlan.id,
        FloorPlan.name,
        Floor.id,
        Floor.name,
        Building.id,
        Building.name,
    )

    res = await db.execute(stmt)
    rows = res.all()

    gateways: List[GatewayUsageDeviceSummary] = []

    total_dwell_seconds = 0
    total_sessions = 0
    total_devices = 0
    first_session_at: Optional[datetime] = None
    last_session_at: Optional[datetime] = None

    for row in rows:
        td = int(row.total_dwell_seconds or 0)
        sc = int(row.sessions_count or 0)
        up = int(row.unique_people_count or 0)

        total_dwell_seconds += td
        total_sessions += sc
        total_devices += 1

        if row.first_session_at and (
            first_session_at is None or row.first_session_at < first_session_at
        ):
            first_session_at = row.first_session_at
        if row.last_session_at and (
            last_session_at is None or row.last_session_at > last_session_at
        ):
            last_session_at = row.last_session_at

        gateways.append(
            GatewayUsageDeviceSummary(
                device_id=row.device_id,
                device_name=row.device_name,
                device_mac_address=row.device_mac_address,
                building_id=row.building_id,
                building_name=row.building_name,
                floor_id=row.floor_id,
                floor_name=row.floor_name,
                floor_plan_id=row.floor_plan_id,
                floor_plan_name=row.floor_plan_name,
                total_dwell_seconds=td,
                sessions_count=sc,
                unique_people_count=up,
                first_session_at=row.first_session_at,
                last_session_at=row.last_session_at,
            )
        )

    # Ordena pelo critério "gateway mais teve pessoas"
    gateways.sort(
        key=lambda g: (g.unique_people_count, g.total_dwell_seconds),
        reverse=True,
    )

    top_device_id = gateways[0].device_id if gateways else None

    from_norm = _normalize_utc_naive(from_ts)
    to_norm = _normalize_utc_naive(to_ts)

    return GatewayUsageSummary(
        from_ts=from_norm,
        to_ts=to_norm,
        total_sessions=total_sessions,
        total_dwell_seconds=total_dwell_seconds,
        total_devices=total_devices,
        gateways=gateways,
        top_device_id=top_device_id,
    )

@router.get(
    "/gateways/{device_id}/time-of-day",
    response_model=GatewayTimeOfDayDistribution,
)
async def get_gateway_time_of_day_distribution(
    device_id: int,
    from_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra sessões a partir desta data/hora",
    ),
    to_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra sessões até esta data/hora",
    ),
    min_duration_seconds: Optional[int] = Query(
        default=None,
        description="Filtra sessões com duração mínima (segundos)",
    ),
    db: AsyncSession = Depends(get_db_session),
):
    # 1) Garante que o device existe
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # 2) Subquery de sessões do gateway específico
    sessions_subq = _build_gateway_sessions_subquery(
        from_ts=from_ts,
        to_ts=to_ts,
        min_duration_seconds=min_duration_seconds,
        device_id=device_id,
    )

    # 3) Agrega por hora do dia
    hour_expr = func.extract(
        "hour",
        sessions_subq.c.started_at,
    ).label("hour")

    stmt = (
        select(
            hour_expr,
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds),
                0,
            ).label("total_dwell_seconds"),
            func.count().label("sessions_count"),
            func.count(
                func.distinct(Person.id)
            ).label("unique_people_count"),
        )
        .select_from(sessions_subq)
        .join(Tag, Tag.id == sessions_subq.c.tag_id, isouter=True)
        .join(Person, Person.id == Tag.person_id, isouter=True)
        .group_by(hour_expr)
        .order_by(hour_expr)
    )

    res = await db.execute(stmt)
    rows = res.all()

    buckets: List[GatewayTimeOfDayBucket] = []

    for row in rows:
        hour_int = int(row.hour)
        buckets.append(
            GatewayTimeOfDayBucket(
                hour=hour_int,
                total_dwell_seconds=int(row.total_dwell_seconds or 0),
                sessions_count=int(row.sessions_count or 0),
                unique_people_count=int(row.unique_people_count or 0),
            )
        )

    from_norm = _normalize_utc_naive(from_ts)
    to_norm = _normalize_utc_naive(to_ts)

    return GatewayTimeOfDayDistribution(
        device_id=device.id,
        device_name=device.name,
        from_ts=from_norm,
        to_ts=to_norm,
        buckets=buckets,
    )

@router.get("/person/{person_id}/summary", response_model=dict)
async def person_presence_summary(
    person_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    min_duration_seconds: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Resumo de presença de UMA pessoa (por TAG vinculada) no período.
    Shape compatível com o PersonPresenceSummary do frontend.
    """

    # normaliza datas pra UTC naive (igual ao resto)
    norm_from = _normalize_utc_naive(from_ts)
    norm_to = _normalize_utc_naive(to_ts)

    person_obj = await db.get(Person, person_id)
    if not person_obj:
        raise HTTPException(status_code=404, detail="Person not found")

    # base: sessões da pessoa (via Tag.person_id)
    base_stmt = (
        select(
            PresenceSession.id.label("id"),
            PresenceSession.device_id.label("device_id"),
            PresenceSession.tag_id.label("tag_id"),
            PresenceSession.started_at.label("started_at"),
            PresenceSession.ended_at.label("ended_at"),
            PresenceSession.duration_seconds.label("duration_seconds"),
        )
        .join(Tag, Tag.id == PresenceSession.tag_id)
        .where(Tag.person_id == person_id)
    )

    base_stmt = _apply_base_filters(
        base_stmt,
        from_ts=norm_from,
        to_ts=norm_to,
        device_id=None,
        tag_id=None,
        min_duration_seconds=min_duration_seconds,
    )

    sessions_subq = base_stmt.subquery("person_sessions")

    # resumo agregado
    summary_stmt = select(
        func.coalesce(func.count(), 0).label("total_sessions"),
        func.coalesce(func.sum(sessions_subq.c.duration_seconds), 0).label("total_dwell_seconds"),
        func.min(sessions_subq.c.started_at).label("first_session_at"),
        func.max(sessions_subq.c.ended_at).label("last_session_at"),
    )

    res = await db.execute(summary_stmt)
    row = res.one_or_none()

    # nenhum dado no período para essa pessoa
    if not row or int(row.total_sessions or 0) == 0:
        return {
            "person_id": person_obj.id,
            "person_full_name": person_obj.full_name,
            "from_ts": from_ts,
            "to_ts": to_ts,
            "total_dwell_seconds": 0,
            "total_sessions": 0,
            "first_session_at": None,
            "last_session_at": None,
            "dwell_by_device": [],
            "top_device_id": None,
        }

    # dwell por gateway
    devices_stmt = (
        select(
            sessions_subq.c.device_id,
            Device.name.label("device_name"),
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds), 0
            ).label("total_dwell_seconds"),
            func.count().label("sessions_count"),
        )
        .join(Device, Device.id == sessions_subq.c.device_id, isouter=True)
        .group_by(sessions_subq.c.device_id, Device.name)
        .order_by(func.sum(sessions_subq.c.duration_seconds).desc())
    )

    dev_res = await db.execute(devices_stmt)
    dev_rows = dev_res.fetchall()

    dwell_by_device = []
    top_device_id: Optional[int] = None

    for idx, d in enumerate(dev_rows):
        if idx == 0:
            top_device_id = d.device_id

        dwell_by_device.append(
            {
                "device_id": d.device_id,
                "device_name": d.device_name or f"Gateway {d.device_id}",
                # por enquanto ids/nome de prédio/andar/planta ficam None (opcional no schema TS)
                "building_id": None,
                "building_name": None,
                "floor_id": None,
                "floor_name": None,
                "floor_plan_id": None,
                "floor_plan_name": None,
                "total_dwell_seconds": int(d.total_dwell_seconds or 0),
                "sessions_count": int(d.sessions_count or 0),
            }
        )

    return {
        "person_id": person_obj.id,
        "person_full_name": person_obj.full_name,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "total_dwell_seconds": int(row.total_dwell_seconds or 0),
        "total_sessions": int(row.total_sessions or 0),
        "first_session_at": row.first_session_at,
        "last_session_at": row.last_session_at,
        "dwell_by_device": dwell_by_device,
        "top_device_id": top_device_id,
    }


@router.get("/person/{person_id}/time-distribution/hour-of-day", response_model=dict)
async def person_time_distribution_hour_of_day(
    person_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    min_duration_seconds: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Distribuição do tempo da pessoa por hora do dia (0..23).
    Shape compatível com PersonTimeOfDayDistribution do frontend.
    """

    norm_from = _normalize_utc_naive(from_ts)
    norm_to = _normalize_utc_naive(to_ts)

    person_obj = await db.get(Person, person_id)
    if not person_obj:
        raise HTTPException(status_code=404, detail="Person not found")

    base_stmt = (
        select(
            PresenceSession.id.label("id"),
            PresenceSession.device_id.label("device_id"),
            PresenceSession.tag_id.label("tag_id"),
            PresenceSession.started_at.label("started_at"),
            PresenceSession.ended_at.label("ended_at"),
            PresenceSession.duration_seconds.label("duration_seconds"),
        )
        .join(Tag, Tag.id == PresenceSession.tag_id)
        .where(Tag.person_id == person_id)
    )

    base_stmt = _apply_base_filters(
        base_stmt,
        from_ts=norm_from,
        to_ts=norm_to,
        device_id=None,
        tag_id=None,
        min_duration_seconds=min_duration_seconds,
    )

    sessions_subq = base_stmt.subquery("person_sessions_hour")

    # agrupa pela hora de started_at (0..23)
    hour_expr = func.date_part("hour", sessions_subq.c.started_at)

    buckets_stmt = (
        select(
            hour_expr.label("hour"),
            func.coalesce(func.sum(sessions_subq.c.duration_seconds), 0).label("total_dwell_seconds"),
            func.count().label("sessions_count"),
        )
        .group_by(hour_expr)
        .order_by(hour_expr)
    )

    res = await db.execute(buckets_stmt)
    rows = res.fetchall()

    by_hour: Dict[int, Any] = {int(r.hour): r for r in rows}

    buckets = []
    for h in range(24):
        r = by_hour.get(h)
        if r:
            buckets.append(
                {
                    "hour": h,
                    "total_dwell_seconds": int(r.total_dwell_seconds or 0),
                    "sessions_count": int(r.sessions_count or 0),
                }
            )
        else:
            buckets.append(
                {
                    "hour": h,
                    "total_dwell_seconds": 0,
                    "sessions_count": 0,
                }
            )

    return {
        "person_id": person_obj.id,
        "person_full_name": person_obj.full_name,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "buckets": buckets,
    }

@router.get(
    "/person/{person_id}/time-distribution/hour-by-gateway",
    response_model=PersonTimeOfDayByGateway,
)
async def person_time_distribution_hour_by_gateway(
    person_id: int,
    from_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra sessões a partir desta data/hora",
    ),
    to_ts: Optional[datetime] = Query(
        default=None,
        description="Filtra sessões até esta data/hora",
    ),
    min_duration_seconds: Optional[int] = Query(
        default=None,
        description="Filtra sessões com duração mínima (segundos)",
    ),
    db: AsyncSession = Depends(get_db_session),
) -> PersonTimeOfDayByGateway:
    """
    Distribuição do tempo da pessoa por HORA (0..23) E por GATEWAY.

    Cada bucket = (hour, device_id) com o total de dwell_seconds e
    quantidade de sessões nesse gateway naquele horário.
    """

    # garante que a pessoa existe
    person_obj = await db.get(Person, person_id)
    if not person_obj:
        raise HTTPException(status_code=404, detail="Person not found")

    # reaproveita a subquery genérica de sessões da pessoa
    sessions_subq = _build_person_sessions_subquery(
        person_id=person_id,
        from_ts=from_ts,
        to_ts=to_ts,
        min_duration_seconds=min_duration_seconds,
    )

    # hora do dia (0..23) – usando date_part como você já faz
    hour_expr = func.date_part("hour", sessions_subq.c.started_at).label("hour")

    stmt = (
        select(
            hour_expr,
            sessions_subq.c.device_id.label("device_id"),
            Device.name.label("device_name"),
            func.coalesce(
                func.sum(sessions_subq.c.duration_seconds),
                0,
            ).label("total_dwell_seconds"),
            func.count().label("sessions_count"),
        )
        .select_from(sessions_subq)
        .join(Device, Device.id == sessions_subq.c.device_id, isouter=True)
        .group_by(
            hour_expr,
            sessions_subq.c.device_id,
            Device.name,
        )
        .order_by(hour_expr, Device.name)
    )

    res = await db.execute(stmt)
    rows = res.fetchall()

    buckets: list[PersonHourByGatewayBucket] = []

    for r in rows:
        hour_int = int(r.hour)
        buckets.append(
            PersonHourByGatewayBucket(
                hour=hour_int,
                device_id=r.device_id,
                device_name=r.device_name or (f"Gateway {r.device_id}" if r.device_id else None),
                total_dwell_seconds=int(r.total_dwell_seconds or 0),
                sessions_count=int(r.sessions_count or 0),
            )
        )

    from_norm = _normalize_utc_naive(from_ts)
    to_norm = _normalize_utc_naive(to_ts)

    return PersonTimeOfDayByGateway(
        person_id=person_obj.id,
        person_full_name=person_obj.full_name,
        from_ts=from_norm,
        to_ts=to_norm,
        buckets=buckets,
    )