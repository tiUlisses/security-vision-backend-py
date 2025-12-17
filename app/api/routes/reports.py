# app/api/routes/reports.py
"""
Relatórios de RTLS (PresenceSession + AlertEvent)

Este módulo concentra endpoints de relatórios para:
- Pessoas (tempo por gateway, heatmaps por hora/dia, timeline, alertas)
- Gateways (uso, heatmap 24h, ocupação por buckets, pico de simultaneidade)
- Prédios (consolidado + distribuição temporal + alertas)

Princípios desta versão:
- Presença sempre baseada em PresenceSession (view) para consistência.
- Janela temporal sempre normalizada para UTC *naive* (compatível com TIMESTAMP WITHOUT TIME ZONE).
- Métricas por hora/dia usam overlap real em buckets (interseção sessão x bucket),
  e não apenas a hora de started_at.
- Endpoints novos ficam aqui, mas modelos Pydantic "leves" são definidos localmente
  quando ainda não existem em app/schemas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, literal, or_, select, text, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.crud.presence_session import presence_session
from app.models.alert_event import AlertEvent
from app.models.building import Building
from app.models.device import Device
from app.models.floor import Floor
from app.models.floor_plan import FloorPlan
from app.models.person import Person
from app.models.person_group import PersonGroup, person_group_memberships
from app.models.presence_session import PresenceSession
from app.models.tag import Tag
from app.schemas.gateway_report import (
    GatewayTimeOfDayBucket,
    GatewayTimeOfDayDistribution,
    GatewayUsageDeviceSummary,
    GatewayUsageSummary,
)
from app.schemas.person_report import (
    GroupDwellByDevice,
    GroupPersonDwellSummary,
    PersonAlertsReport,
    PersonAlertByDevice,
    PersonAlertByType,
    PersonAlertEvent,
    PersonDayOfWeekBucket,
    PersonDayOfWeekDistribution,
    PersonDwellByDevice,
    PersonGroupPresenceSummary,
    PersonHourByGatewayBucket,
    PersonPresenceSummary,
    PersonTimeDistributionBucket,
    PersonTimeDistributionCalendar,
    PersonTimeOfDayByGateway,
    PersonTimeOfDayBucket,
    PersonTimeOfDayDistribution,
    PersonTimelineSession,
)
from app.schemas.presence_session import PresenceSessionRead

router = APIRouter(tags=["reports"])


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Converte datetime aware para UTC naive (remove tzinfo)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class TimeWindow:
    from_ts: Optional[datetime]
    to_ts: Optional[datetime]


def _coerce_window(
    *,
    from_ts: Optional[datetime],
    to_ts: Optional[datetime],
    default_hours: Optional[int] = None,
) -> TimeWindow:
    """Normaliza para UTC naive e aplica janela default se vazio."""
    f = _normalize_utc_naive(from_ts)
    t = _normalize_utc_naive(to_ts)

    if f is None and t is None and default_hours is not None:
        now = _now_utc_naive()
        return TimeWindow(from_ts=now - timedelta(hours=default_hours), to_ts=now)

    return TimeWindow(from_ts=f, to_ts=t)


def _presence_intersects_window(*, started_col, ended_col, window: TimeWindow):
    # ended_at NULL = sessão aberta => considerar como "intersecta" se started_at estiver no range
    if window.from_ts is not None and window.to_ts is not None:
        return and_(
            started_col <= window.to_ts,
            or_(ended_col.is_(None), ended_col >= window.from_ts),
        )
    if window.from_ts is not None:
        return or_(ended_col.is_(None), ended_col >= window.from_ts)
    if window.to_ts is not None:
        return started_col <= window.to_ts
    return text("TRUE")


def _overlap_seconds_expr(*, started_col, ended_col, window_from, window_to):
    # ended_at NULL => assume "fim" como window_to (se existir) senão NOW
    if window_to is not None:
        end_base = func.coalesce(ended_col, literal(window_to))
    else:
        # timestamp UTC naive
        end_base = func.coalesce(ended_col, func.timezone("utc", func.now()))

    start_eff = started_col
    end_eff = end_base

    if window_from is not None:
        start_eff = func.greatest(start_eff, window_from)
    if window_to is not None:
        end_eff = func.least(end_eff, window_to)

    raw = func.extract("epoch", end_eff - start_eff)
    return func.greatest(raw, 0)


def _require_finite_window(window: TimeWindow, *, detail: str) -> Tuple[datetime, datetime]:
    if window.from_ts is None or window.to_ts is None:
        raise HTTPException(status_code=400, detail=detail)
    return window.from_ts, window.to_ts


def _hour_buckets_subq(window: TimeWindow):
    """Subquery com bucket_start por hora, de from_ts até to_ts (inclusivo)."""
    from_ts, to_ts = _require_finite_window(
        window, detail="from_ts e to_ts são obrigatórios para endpoints baseados em buckets"
    )
    start = func.date_trunc("hour", from_ts)
    stop = func.date_trunc("hour", to_ts)
    bucket_start = func.generate_series(start, stop, text("interval '1 hour'")).label("bucket_start")
    return select(bucket_start).subquery("hour_buckets")


def _bucket_overlap_seconds_hour(*, sess_start, sess_end, bucket_start):
    bucket_end = bucket_start + text("interval '1 hour'")
    sess_end_eff = func.coalesce(sess_end, bucket_end)  # sessão aberta => até o fim do bucket
    raw = func.extract(
        "epoch",
        func.least(sess_end_eff, bucket_end) - func.greatest(sess_start, bucket_start),
    )
    return func.greatest(raw, 0)


def _calendar_step_interval(granularity: str) -> str:
    if granularity == "day":
        return "interval '1 day'"
    if granularity == "week":
        return "interval '1 week'"
    if granularity == "month":
        return "interval '1 month'"
    if granularity == "year":
        return "interval '1 year'"
    raise ValueError("Invalid granularity")


def _calendar_buckets_subq(window: TimeWindow, granularity: Literal["day", "week", "month", "year"]):
    """Subquery com bucket_start por granularidade (day/week/month/year)."""
    from_ts, to_ts = _require_finite_window(
        window, detail="from_ts e to_ts são obrigatórios para endpoints baseados em buckets"
    )
    step = _calendar_step_interval(granularity)
    bucket_start = func.generate_series(
        func.date_trunc(granularity, from_ts),
        func.date_trunc(granularity, to_ts),
        text(step),
    ).label("bucket_start")
    return select(bucket_start).subquery("cal_buckets")


def _bucket_overlap_seconds_generic(*, sess_start, sess_end, bucket_start, step_interval_sql: str):
    bucket_end = bucket_start + text(step_interval_sql)
    raw = func.extract(
        "epoch",
        func.least(sess_end, bucket_end) - func.greatest(sess_start, bucket_start),
    )
    return func.greatest(raw, 0)


# ---------------------------------------------------------------------------
# Local response models (novos endpoints)
# ---------------------------------------------------------------------------


class TimeBucket(BaseModel):
    bucket_start: datetime
    total_dwell_seconds: int = 0
    sessions_count: int = 0
    unique_tags_count: int = 0
    unique_people_count: int = 0


class PeakBucket(BaseModel):
    bucket_start: datetime
    unique_people_count: int


class GatewayOccupancyReport(BaseModel):
    device_id: int
    device_name: Optional[str] = None
    from_ts: datetime
    to_ts: datetime
    buckets: List[TimeBucket]
    peak: Optional[PeakBucket] = None
    avg_dwell_seconds: Optional[float] = None
    p50_dwell_seconds: Optional[float] = None
    p95_dwell_seconds: Optional[float] = None


class ConcurrencyBucket(BaseModel):
    bucket_start: datetime
    peak_concurrency_people: int = 0


class GatewayConcurrencyReport(BaseModel):
    device_id: int
    device_name: Optional[str] = None
    from_ts: datetime
    to_ts: datetime
    buckets: List[ConcurrencyBucket]


class BuildingSummaryItem(BaseModel):
    device_id: Optional[int] = None
    device_name: Optional[str] = None
    sessions_count: int = 0
    total_dwell_seconds: int = 0
    unique_people_count: int = 0


class BuildingSummaryReport(BaseModel):
    building_id: int
    building_name: str
    from_ts: Optional[datetime] = None
    to_ts: Optional[datetime] = None
    total_sessions: int = 0
    total_dwell_seconds: int = 0
    unique_people_count: int = 0
    unique_tags_count: int = 0
    avg_dwell_seconds: Optional[float] = None
    top_gateways_by_sessions: List[BuildingSummaryItem] = Field(default_factory=list)
    top_gateways_by_dwell: List[BuildingSummaryItem] = Field(default_factory=list)


class AlertTypeCount(BaseModel):
    event_type: str
    alerts_count: int


class AlertsSummaryReport(BaseModel):
    scope: Literal["gateway", "building"]
    scope_id: int
    from_ts: Optional[datetime] = None
    to_ts: Optional[datetime] = None
    total_alerts: int
    by_type: List[AlertTypeCount]


# ---------------------------------------------------------------------------
# Raw presence sessions
# ---------------------------------------------------------------------------


@router.get("/dwell-sessions", response_model=List[PresenceSessionRead])
async def list_dwell_sessions(
    skip: int = 0,
    limit: int = 100,
    device_id: int | None = Query(default=None),
    tag_id: int | None = Query(default=None),
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Lista sessões de presença (view presence_sessions)."""
    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=None)
    sessions = await presence_session.get_multi(
        db,
        skip=skip,
        limit=limit,
        device_id=device_id,
        tag_id=tag_id,
        from_ts=window.from_ts,
        to_ts=window.to_ts,
    )
    return sessions


# ---------------------------------------------------------------------------
# Overview (global)
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=dict)
async def reports_overview(
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    device_id: int | None = Query(default=None),
    tag_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Overview para dashboards usando PresenceSession e overlap clipado."""
    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24 * 7)

    base = select(
        PresenceSession.device_id,
        PresenceSession.tag_id,
        PresenceSession.started_at,
        PresenceSession.ended_at,
    ).where(
        PresenceSession.device_id.is_not(None),
        PresenceSession.tag_id.is_not(None),
        _presence_intersects_window(
            started_col=PresenceSession.started_at,
            ended_col=PresenceSession.ended_at,
            window=window,
        ),
    )

    if device_id is not None:
        base = base.where(PresenceSession.device_id == device_id)
    if tag_id is not None:
        base = base.where(PresenceSession.tag_id == tag_id)

    sessions_subq = base.subquery("sessions")

    overlap = _overlap_seconds_expr(
        started_col=sessions_subq.c.started_at,
        ended_col=sessions_subq.c.ended_at,
        window_from=window.from_ts,
        window_to=window.to_ts,
    )
    summary_stmt = (
        select(
            func.count().label("total_sessions"),
            func.count(func.distinct(sessions_subq.c.tag_id)).label("total_unique_tags"),
            func.count(func.distinct(sessions_subq.c.device_id)).label("total_unique_devices"),
            func.count(func.distinct(Person.id)).label("total_unique_people"),
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
            func.avg(overlap).label("avg_dwell_seconds"),
            func.min(sessions_subq.c.started_at).label("first_session_at"),
            func.max(sessions_subq.c.ended_at).label("last_session_at"),
        )
        .select_from(sessions_subq)
        .join(Tag, Tag.id == sessions_subq.c.tag_id, isouter=True)
        .join(Person, Person.id == Tag.person_id, isouter=True)
    )

    sres = await db.execute(summary_stmt)
    srow = sres.one()

    summary = {
        "from_ts": window.from_ts,
        "to_ts": window.to_ts,
        "total_sessions": int(srow.total_sessions or 0),
        "total_unique_tags": int(srow.total_unique_tags or 0),
        "total_unique_devices": int(srow.total_unique_devices or 0),
        "total_unique_people": int(getattr(srow, "total_unique_people", 0) or 0),
        "total_dwell_seconds": int(srow.total_dwell_seconds or 0),
        "avg_dwell_seconds": float(srow.avg_dwell_seconds or 0.0) if srow.avg_dwell_seconds is not None else 0.0,
        "first_session_at": srow.first_session_at,
        "last_session_at": srow.last_session_at,
    }

    top_devices_stmt = (
        select(
            sessions_subq.c.device_id.label("device_id"),
            Device.name.label("device_name"),
            func.count().label("total_sessions"),
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
        )
        .select_from(sessions_subq)
        .join(Device, Device.id == sessions_subq.c.device_id, isouter=True)
        .group_by(sessions_subq.c.device_id, Device.name)
        .order_by(func.coalesce(func.sum(overlap), 0).desc())
        .limit(10)
    )
    td_res = await db.execute(top_devices_stmt)
    top_devices = [
        {
            "device_id": r.device_id,
            "device_name": r.device_name or f"Device {r.device_id}",
            "total_sessions": int(r.total_sessions or 0),
            "total_dwell_seconds": int(r.total_dwell_seconds or 0),
        }
        for r in td_res.all()
        if r.device_id is not None
    ]

    top_people_stmt = (
        select(
            Person.id.label("person_id"),
            Person.full_name.label("person_name"),
            func.count().label("total_sessions"),
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
        )
        .select_from(sessions_subq)
        .join(Tag, Tag.id == sessions_subq.c.tag_id, isouter=True)
        .join(Person, Person.id == Tag.person_id, isouter=True)
        .where(Person.id.is_not(None))
        .group_by(Person.id, Person.full_name)
        .order_by(func.coalesce(func.sum(overlap), 0).desc())
        .limit(10)
    )
    tp_res = await db.execute(top_people_stmt)
    top_people = [
        {
            "person_id": r.person_id,
            "person_name": r.person_name or f"Pessoa {r.person_id}",
            "total_sessions": int(r.total_sessions or 0),
            "total_dwell_seconds": int(r.total_dwell_seconds or 0),
        }
        for r in tp_res.all()
        if r.person_id is not None
    ]

    top_buildings_stmt = (
        select(
            Building.id.label("building_id"),
            Building.name.label("building_name"),
            func.count().label("total_sessions"),
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
        )
        .select_from(sessions_subq)
        .join(Device, Device.id == sessions_subq.c.device_id, isouter=True)
        .join(FloorPlan, FloorPlan.id == Device.floor_plan_id, isouter=True)
        .join(Floor, Floor.id == FloorPlan.floor_id, isouter=True)
        .join(Building, Building.id == Floor.building_id, isouter=True)
        .group_by(Building.id, Building.name)
        .order_by(func.coalesce(func.sum(overlap), 0).desc())
        .limit(10)
    )
    tb_res = await db.execute(top_buildings_stmt)
    top_buildings = [
        {
            "building_id": r.building_id,
            "building_name": r.building_name or "Sem prédio",
            "total_sessions": int(r.total_sessions or 0),
            "total_dwell_seconds": int(r.total_dwell_seconds or 0),
        }
        for r in tb_res.all()
        if r.building_id is not None
    ]
    # Top floors
    top_floors_stmt = (
        select(
            Floor.id.label("floor_id"),
            Floor.name.label("floor_name"),
            Building.id.label("building_id"),
            Building.name.label("building_name"),
            func.count().label("total_sessions"),
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
        )
        .select_from(sessions_subq)
        .join(Device, Device.id == sessions_subq.c.device_id, isouter=True)
        .join(FloorPlan, FloorPlan.id == Device.floor_plan_id, isouter=True)
        .join(Floor, Floor.id == FloorPlan.floor_id, isouter=True)
        .join(Building, Building.id == Floor.building_id, isouter=True)
        .group_by(Floor.id, Floor.name, Building.id, Building.name)
        .order_by(func.coalesce(func.sum(overlap), 0).desc())
        .limit(10)
    )

    tf_res = await db.execute(top_floors_stmt)
    top_floors = [
        {
            "floor_id": r.floor_id,
            "floor_name": r.floor_name or f"Andar {r.floor_id}",
            "building_id": r.building_id,
            "building_name": r.building_name or "Sem prédio",
            "total_sessions": int(r.total_sessions or 0),
            "total_dwell_seconds": int(r.total_dwell_seconds or 0),
        }
        for r in tf_res.all()
        if r.floor_id is not None
    ]

    # Top groups
    top_groups_stmt = (
        select(
            PersonGroup.id.label("group_id"),
            PersonGroup.name.label("group_name"),
            func.count().label("total_sessions"),
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
        )
        .select_from(sessions_subq)
        .join(Tag, Tag.id == sessions_subq.c.tag_id, isouter=True)
        .join(Person, Person.id == Tag.person_id, isouter=True)
        .join(person_group_memberships, person_group_memberships.c.person_id == Person.id, isouter=True)
        .join(PersonGroup, PersonGroup.id == person_group_memberships.c.group_id, isouter=True)
        .where(PersonGroup.id.is_not(None))
        .group_by(PersonGroup.id, PersonGroup.name)
        .order_by(func.coalesce(func.sum(overlap), 0).desc())
        .limit(10)
    )

    tg_res = await db.execute(top_groups_stmt)
    top_groups = [
        {
            "group_id": r.group_id,
            "group_name": r.group_name or f"Grupo {r.group_id}",
            "total_sessions": int(r.total_sessions or 0),
            "total_dwell_seconds": int(r.total_dwell_seconds or 0),
        }
        for r in tg_res.all()
        if r.group_id is not None
    ]

    return {
        "summary": summary,
        "top_buildings": top_buildings,
        "top_floors": top_floors,
        "top_groups": top_groups,
        "top_devices": top_devices,
        "top_people": top_people,
    }
# ---------------------------------------------------------------------------
# Person group summary
# ---------------------------------------------------------------------------


def _build_group_sessions_subquery(
    group_id: int,
    *,
    window: TimeWindow,
    min_duration_seconds: Optional[int],
):
    stmt = (
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
        .select_from(PresenceSession)
        .join(Tag, Tag.id == PresenceSession.tag_id)
        .join(Person, Person.id == Tag.person_id)
        .join(person_group_memberships, person_group_memberships.c.person_id == Person.id)
        .where(person_group_memberships.c.group_id == group_id)
        .where(
            _presence_intersects_window(
                started_col=PresenceSession.started_at,
                ended_col=PresenceSession.ended_at,
                window=window,
            )
        )
    )

    if min_duration_seconds is not None:
        stmt = stmt.where(PresenceSession.duration_seconds >= min_duration_seconds)

    return stmt.subquery("group_sessions")


@router.get("/person-group/{group_id}/summary", response_model=PersonGroupPresenceSummary)
async def get_person_group_presence_summary(
    group_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    min_duration_seconds: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    group = await db.get(PersonGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Person group not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24 * 7)
    sessions_subq = _build_group_sessions_subquery(group_id, window=window, min_duration_seconds=min_duration_seconds)

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
            func.coalesce(func.sum(sessions_subq.c.duration_seconds), 0).label("total_dwell_seconds"),
            func.count(func.distinct(sessions_subq.c.person_id)).label("unique_people_count"),
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
        .order_by(func.coalesce(func.sum(sessions_subq.c.duration_seconds), 0).desc())
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

        if row.first_session_at and (first_session_at is None or row.first_session_at < first_session_at):
            first_session_at = row.first_session_at
        if row.last_session_at and (last_session_at is None or row.last_session_at > last_session_at):
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

    by_person_stmt = (
        select(
            sessions_subq.c.person_id.label("person_id"),
            sessions_subq.c.person_full_name.label("person_full_name"),
            func.coalesce(func.sum(sessions_subq.c.duration_seconds), 0).label("total_dwell_seconds"),
            func.count().label("sessions_count"),
        )
        .select_from(sessions_subq)
        .group_by(sessions_subq.c.person_id, sessions_subq.c.person_full_name)
        .order_by(func.coalesce(func.sum(sessions_subq.c.duration_seconds), 0).desc())
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
            total_unique_people_set.add(int(row.person_id))

    return PersonGroupPresenceSummary(
        group_id=group.id,
        group_name=group.name,
        from_ts=window.from_ts,
        to_ts=window.to_ts,
        total_dwell_seconds=total_dwell_seconds,
        total_sessions=total_sessions,
        total_unique_people=len(total_unique_people_set),
        first_session_at=first_session_at,
        last_session_at=last_session_at,
        dwell_by_device=dwell_by_device,
        dwell_by_person=dwell_by_person,
        top_device_id=top_device_id,
    )


# ---------------------------------------------------------------------------
# Person reports
# ---------------------------------------------------------------------------


def _person_sessions_subq(
    person_id: int,
    *,
    window: TimeWindow,
    min_duration_seconds: Optional[int],
):
    stmt = (
        select(
            PresenceSession.id.label("id"),
            PresenceSession.device_id.label("device_id"),
            PresenceSession.tag_id.label("tag_id"),
            PresenceSession.started_at.label("started_at"),
            PresenceSession.ended_at.label("ended_at"),
            PresenceSession.duration_seconds.label("duration_seconds"),
            PresenceSession.samples_count.label("samples_count"),
        )
        .select_from(PresenceSession)
        .join(Tag, Tag.id == PresenceSession.tag_id)
        .where(Tag.person_id == person_id)
        .where(
            _presence_intersects_window(
                started_col=PresenceSession.started_at,
                ended_col=PresenceSession.ended_at,
                window=window,
            )
        )
    )
    if min_duration_seconds is not None:
        stmt = stmt.where(PresenceSession.duration_seconds >= min_duration_seconds)
    return stmt.subquery("person_sessions")


@router.get("/person/{person_id}/summary", response_model=PersonPresenceSummary)
async def get_person_presence_summary(
    person_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    min_duration_seconds: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    person_obj = await db.get(Person, person_id)
    if not person_obj:
        raise HTTPException(status_code=404, detail="Person not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24 * 7)
    sessions_subq = _person_sessions_subq(person_id, window=window, min_duration_seconds=min_duration_seconds)

    overlap = _overlap_seconds_expr(
        started_col=sessions_subq.c.started_at,
        ended_col=sessions_subq.c.ended_at,
        window_from=window.from_ts,
        window_to=window.to_ts,
    )

    summary_stmt = select(
        func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
        func.count().label("total_sessions"),
        func.min(sessions_subq.c.started_at).label("first_session_at"),
        func.max(sessions_subq.c.ended_at).label("last_session_at"),
    ).select_from(sessions_subq)

    sres = await db.execute(summary_stmt)
    srow = sres.one()

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
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
            func.count().label("sessions_count"),
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
        .order_by(func.coalesce(func.sum(overlap), 0).desc())
    )

    dres = await db.execute(by_device_stmt)
    rows = dres.all()

    dwell_by_device: List[PersonDwellByDevice] = []
    top_device_id: Optional[int] = None

    for idx, r in enumerate(rows):
        if idx == 0:
            top_device_id = r.device_id
        dwell_by_device.append(
            PersonDwellByDevice(
                device_id=r.device_id,
                device_name=r.device_name,
                building_id=r.building_id,
                building_name=r.building_name,
                floor_id=r.floor_id,
                floor_name=r.floor_name,
                floor_plan_id=r.floor_plan_id,
                floor_plan_name=r.floor_plan_name,
                total_dwell_seconds=int(r.total_dwell_seconds or 0),
                sessions_count=int(r.sessions_count or 0),
            )
        )

    return PersonPresenceSummary(
        person_id=person_obj.id,
        person_full_name=person_obj.full_name,
        from_ts=window.from_ts,
        to_ts=window.to_ts,
        total_dwell_seconds=int(srow.total_dwell_seconds or 0),
        total_sessions=int(srow.total_sessions or 0),
        first_session_at=srow.first_session_at,
        last_session_at=srow.last_session_at,
        dwell_by_device=dwell_by_device,
        top_device_id=top_device_id,
    )


@router.get("/person/{person_id}/timeline", response_model=List[PersonTimelineSession])
async def get_person_timeline(
    person_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    min_duration_seconds: Optional[int] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db_session),
):
    person_obj = await db.get(Person, person_id)
    if not person_obj:
        raise HTTPException(status_code=404, detail="Person not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24 * 7)
    sessions_subq = _person_sessions_subq(person_id, window=window, min_duration_seconds=min_duration_seconds)

    overlap = _overlap_seconds_expr(
        started_col=sessions_subq.c.started_at,
        ended_col=sessions_subq.c.ended_at,
        window_from=window.from_ts,
        window_to=window.to_ts,
    )

    stmt = (
        select(
            sessions_subq.c.device_id,
            Device.name.label("device_name"),
            sessions_subq.c.started_at,
            sessions_subq.c.ended_at,
            overlap.label("duration_seconds"),
            sessions_subq.c.samples_count,
        )
        .select_from(sessions_subq)
        .join(Device, Device.id == sessions_subq.c.device_id, isouter=True)
        .order_by(sessions_subq.c.started_at.desc())
        .limit(limit)
    )

    res = await db.execute(stmt)
    rows = res.all()

    return [
        PersonTimelineSession(
            device_id=r.device_id,
            device_name=r.device_name,
            started_at=r.started_at,
            ended_at=r.ended_at,
            duration_seconds=int(r.duration_seconds or 0),
            samples_count=int(r.samples_count or 0),
        )
        for r in rows
    ]


@router.get("/person/{person_id}/time-distribution/calendar", response_model=PersonTimeDistributionCalendar)
async def get_person_time_distribution_calendar(
    person_id: int,
    granularity: Literal["day", "week", "month", "year"] = Query(default="day"),
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    min_duration_seconds: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    person_obj = await db.get(Person, person_id)
    if not person_obj:
        raise HTTPException(status_code=404, detail="Person not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24 * 30)
    sessions_subq = _person_sessions_subq(person_id, window=window, min_duration_seconds=min_duration_seconds)

    overlap = _overlap_seconds_expr(
        started_col=sessions_subq.c.started_at,
        ended_col=sessions_subq.c.ended_at,
        window_from=window.from_ts,
        window_to=window.to_ts,
    )

    bucket_expr = func.date_trunc(granularity, sessions_subq.c.started_at).label("bucket_start")

    stmt = (
        select(
            bucket_expr,
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
            func.count().label("sessions_count"),
        )
        .select_from(sessions_subq)
        .group_by(bucket_expr)
        .order_by(bucket_expr)
    )

    res = await db.execute(stmt)
    rows = res.all()

    buckets = [
        PersonTimeDistributionBucket(
            bucket_start=r.bucket_start,
            total_dwell_seconds=int(r.total_dwell_seconds or 0),
            sessions_count=int(r.sessions_count or 0),
        )
        for r in rows
    ]

    return PersonTimeDistributionCalendar(
        person_id=person_obj.id,
        person_full_name=person_obj.full_name,
        from_ts=window.from_ts,
        to_ts=window.to_ts,
        granularity=granularity,
        buckets=buckets,
    )


@router.get("/person/{person_id}/time-distribution/hour-of-day", response_model=PersonTimeOfDayDistribution)
async def get_person_time_distribution_hour_of_day(
    person_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    min_duration_seconds: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    person_obj = await db.get(Person, person_id)
    if not person_obj:
        raise HTTPException(status_code=404, detail="Person not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24)
    _require_finite_window(window, detail="from_ts e to_ts são obrigatórios")

    sessions_subq = _person_sessions_subq(person_id, window=window, min_duration_seconds=min_duration_seconds)
    buckets_subq = _hour_buckets_subq(window)

    overlap = _bucket_overlap_seconds_hour(
        sess_start=sessions_subq.c.started_at,
        sess_end=sessions_subq.c.ended_at,
        bucket_start=buckets_subq.c.bucket_start,
    )

    hour_expr = func.extract("hour", buckets_subq.c.bucket_start).label("hour")

    stmt = (
        select(
            hour_expr,
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
            func.count(func.distinct(sessions_subq.c.id)).label("sessions_count"),
        )
        .select_from(buckets_subq)
        .join(
            sessions_subq,
            and_(
                sessions_subq.c.started_at < (buckets_subq.c.bucket_start + text("interval '1 hour'")),
                sessions_subq.c.ended_at > buckets_subq.c.bucket_start,
            ),
            isouter=True,
        )
        .group_by(hour_expr)
        .order_by(hour_expr)
    )

    res = await db.execute(stmt)
    rows = res.all()

    by_hour: Dict[int, Tuple[int, int]] = {
        int(r.hour): (int(r.total_dwell_seconds or 0), int(r.sessions_count or 0)) for r in rows if r.hour is not None
    }

    buckets = [
        PersonTimeOfDayBucket(
            hour=h,
            total_dwell_seconds=by_hour.get(h, (0, 0))[0],
            sessions_count=by_hour.get(h, (0, 0))[1],
        )
        for h in range(24)
    ]

    return PersonTimeOfDayDistribution(
        person_id=person_obj.id,
        person_full_name=person_obj.full_name,
        from_ts=window.from_ts,
        to_ts=window.to_ts,
        buckets=buckets,
    )


@router.get("/person/{person_id}/time-distribution/day-of-week", response_model=PersonDayOfWeekDistribution)
async def get_person_time_distribution_day_of_week(
    person_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    min_duration_seconds: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    person_obj = await db.get(Person, person_id)
    if not person_obj:
        raise HTTPException(status_code=404, detail="Person not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24 * 30)
    _require_finite_window(window, detail="from_ts e to_ts são obrigatórios")

    sessions_subq = _person_sessions_subq(person_id, window=window, min_duration_seconds=min_duration_seconds)
    buckets_subq = _hour_buckets_subq(window)

    overlap = _bucket_overlap_seconds_hour(
        sess_start=sessions_subq.c.started_at,
        sess_end=sessions_subq.c.ended_at,
        bucket_start=buckets_subq.c.bucket_start,
    )

    dow_expr = func.extract("dow", buckets_subq.c.bucket_start).label("dow")

    stmt = (
        select(
            dow_expr,
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
            func.count(func.distinct(sessions_subq.c.id)).label("sessions_count"),
        )
        .select_from(buckets_subq)
        .join(
            sessions_subq,
            and_(
                sessions_subq.c.started_at < (buckets_subq.c.bucket_start + text("interval '1 hour'")),
                sessions_subq.c.ended_at > buckets_subq.c.bucket_start,
            ),
            isouter=True,
        )
        .group_by(dow_expr)
        .order_by(dow_expr)
    )

    res = await db.execute(stmt)
    rows = res.all()

    by_dow: Dict[int, Tuple[int, int]] = {
        int(r.dow): (int(r.total_dwell_seconds or 0), int(r.sessions_count or 0)) for r in rows if r.dow is not None
    }

    buckets = [
        PersonDayOfWeekBucket(
            day_of_week=d,
            total_dwell_seconds=by_dow.get(d, (0, 0))[0],
            sessions_count=by_dow.get(d, (0, 0))[1],
        )
        for d in range(7)
    ]

    return PersonDayOfWeekDistribution(
        person_id=person_obj.id,
        person_full_name=person_obj.full_name,
        from_ts=window.from_ts,
        to_ts=window.to_ts,
        buckets=buckets,
    )


@router.get("/person/{person_id}/time-distribution/hour-by-gateway", response_model=PersonTimeOfDayByGateway)
async def person_time_distribution_hour_by_gateway(
    person_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    min_duration_seconds: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> PersonTimeOfDayByGateway:
    person_obj = await db.get(Person, person_id)
    if not person_obj:
        raise HTTPException(status_code=404, detail="Person not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24)
    _require_finite_window(window, detail="from_ts e to_ts são obrigatórios")

    sessions_subq = _person_sessions_subq(person_id, window=window, min_duration_seconds=min_duration_seconds)
    buckets_subq = _hour_buckets_subq(window)

    overlap = _bucket_overlap_seconds_hour(
        sess_start=sessions_subq.c.started_at,
        sess_end=sessions_subq.c.ended_at,
        bucket_start=buckets_subq.c.bucket_start,
    )

    hour_expr = func.extract("hour", buckets_subq.c.bucket_start).label("hour")

    stmt = (
        select(
            hour_expr,
            sessions_subq.c.device_id.label("device_id"),
            Device.name.label("device_name"),
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
            func.count(func.distinct(sessions_subq.c.id)).label("sessions_count"),
        )
        .select_from(buckets_subq)
        .join(
            sessions_subq,
            and_(
                sessions_subq.c.started_at < (buckets_subq.c.bucket_start + text("interval '1 hour'")),
                sessions_subq.c.ended_at > buckets_subq.c.bucket_start,
            ),
            isouter=False,
        )
        .join(Device, Device.id == sessions_subq.c.device_id, isouter=True)
        .group_by(hour_expr, sessions_subq.c.device_id, Device.name)
        .order_by(hour_expr, Device.name)
    )

    res = await db.execute(stmt)
    rows = res.all()

    buckets = [
        PersonHourByGatewayBucket(
            hour=int(r.hour),
            device_id=r.device_id,
            device_name=r.device_name or (f"Gateway {r.device_id}" if r.device_id else None),
            total_dwell_seconds=int(r.total_dwell_seconds or 0),
            sessions_count=int(r.sessions_count or 0),
        )
        for r in rows
    ]

    return PersonTimeOfDayByGateway(
        person_id=person_obj.id,
        person_full_name=person_obj.full_name,
        from_ts=window.from_ts,
        to_ts=window.to_ts,
        buckets=buckets,
    )


# ---------------------------------------------------------------------------
# Person alerts
# ---------------------------------------------------------------------------


@router.get("/person/{person_id}/alerts", response_model=PersonAlertsReport)
async def get_person_alerts_report(
    person_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    device_id: Optional[int] = Query(default=None),
    max_events: int = Query(default=1000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db_session),
):
    person = await db.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24 * 30)

    filters = [AlertEvent.person_id == person_id]
    if window.from_ts is not None:
        filters.append(AlertEvent.started_at >= window.from_ts)
    if window.to_ts is not None:
        filters.append(AlertEvent.started_at <= window.to_ts)
    if event_type is not None:
        filters.append(AlertEvent.event_type == event_type)
    if device_id is not None:
        filters.append(AlertEvent.device_id == device_id)

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

    total_alerts = 0
    first_alert_at: Optional[datetime] = None
    last_alert_at: Optional[datetime] = None

    by_type_map: Dict[str, int] = {}
    by_device_map: Dict[Optional[int], Dict[str, Any]] = {}

    events: List[PersonAlertEvent] = []

    for row in rows:
        total_alerts += 1
        started_at = row.started_at

        if started_at:
            if first_alert_at is None or started_at < first_alert_at:
                first_alert_at = started_at
            if last_alert_at is None or started_at > last_alert_at:
                last_alert_at = started_at

        et = row.event_type or "UNKNOWN"
        by_type_map[et] = by_type_map.get(et, 0) + 1

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

    by_type = [PersonAlertByType(event_type=et, alerts_count=count) for et, count in by_type_map.items()]
    by_type.sort(key=lambda x: x.alerts_count, reverse=True)

    by_device = [PersonAlertByDevice(**data) for data in by_device_map.values()]
    by_device.sort(key=lambda x: x.alerts_count, reverse=True)

    return PersonAlertsReport(
        person_id=person.id,
        person_full_name=person.full_name,
        from_ts=window.from_ts,
        to_ts=window.to_ts,
        total_alerts=total_alerts,
        first_alert_at=first_alert_at,
        last_alert_at=last_alert_at,
        by_type=by_type,
        by_device=by_device,
        events=events,
    )


# ---------------------------------------------------------------------------
# Gateway reports
# ---------------------------------------------------------------------------


def _gateway_sessions_subq(
    *,
    window: TimeWindow,
    device_id: Optional[int],
    min_duration_seconds: Optional[int],
):
    stmt = select(
        PresenceSession.id.label("id"),
        PresenceSession.device_id.label("device_id"),
        PresenceSession.tag_id.label("tag_id"),
        PresenceSession.started_at.label("started_at"),
        PresenceSession.ended_at.label("ended_at"),
        PresenceSession.duration_seconds.label("duration_seconds"),
        PresenceSession.samples_count.label("samples_count"),
    ).where(
        _presence_intersects_window(
            started_col=PresenceSession.started_at,
            ended_col=PresenceSession.ended_at,
            window=window,
        )
    )

    if device_id is not None:
        stmt = stmt.where(PresenceSession.device_id == device_id)
    if min_duration_seconds is not None:
        stmt = stmt.where(PresenceSession.duration_seconds >= min_duration_seconds)

    return stmt.subquery("gateway_sessions")


@router.get("/gateways/usage-summary", response_model=GatewayUsageSummary)
async def get_gateway_usage_summary(
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    building_id: Optional[int] = Query(default=None),
    floor_id: Optional[int] = Query(default=None),
    floor_plan_id: Optional[int] = Query(default=None),
    device_id: Optional[int] = Query(default=None),
    min_duration_seconds: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24 * 7)
    sessions_subq = _gateway_sessions_subq(window=window, device_id=device_id, min_duration_seconds=min_duration_seconds)

    overlap = _overlap_seconds_expr(
        started_col=sessions_subq.c.started_at,
        ended_col=sessions_subq.c.ended_at,
        window_from=window.from_ts,
        window_to=window.to_ts,
    )

    stmt = (
        select(
            sessions_subq.c.device_id.label("device_id"),
            Device.name.label("device_name"),
            Device.mac_address.label("device_mac_address"),
            FloorPlan.id.label("floor_plan_id"),
            FloorPlan.name.label("floor_plan_name"),
            Floor.id.label("floor_id"),
            Floor.name.label("floor_name"),
            Building.id.label("building_id"),
            Building.name.label("building_name"),
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
            func.count().label("sessions_count"),
            func.count(func.distinct(Person.id)).label("unique_people_count"),
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

        if row.first_session_at and (first_session_at is None or row.first_session_at < first_session_at):
            first_session_at = row.first_session_at
        if row.last_session_at and (last_session_at is None or row.last_session_at > last_session_at):
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

    gateways.sort(key=lambda g: (g.unique_people_count, g.total_dwell_seconds), reverse=True)
    top_device_id = gateways[0].device_id if gateways else None

    return GatewayUsageSummary(
        from_ts=window.from_ts,
        to_ts=window.to_ts,
        total_sessions=total_sessions,
        total_dwell_seconds=total_dwell_seconds,
        total_devices=total_devices,
        gateways=gateways,
        top_device_id=top_device_id,
    )


@router.get("/gateways/{device_id}/time-of-day", response_model=GatewayTimeOfDayDistribution)
async def get_gateway_time_of_day_distribution(
    device_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    min_duration_seconds: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24 * 7)
    _require_finite_window(window, detail="from_ts e to_ts são obrigatórios")

    sessions_subq = _gateway_sessions_subq(window=window, device_id=device_id, min_duration_seconds=min_duration_seconds)
    buckets_subq = _hour_buckets_subq(window)

    overlap = _bucket_overlap_seconds_hour(
        sess_start=sessions_subq.c.started_at,
        sess_end=sessions_subq.c.ended_at,
        bucket_start=buckets_subq.c.bucket_start,
    )

    hour_expr = func.extract("hour", buckets_subq.c.bucket_start).label("hour")

    stmt = (
        select(
            hour_expr,
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
            func.count(func.distinct(sessions_subq.c.id)).label("sessions_count"),
            func.count(func.distinct(Person.id)).label("unique_people_count"),
        )
        .select_from(buckets_subq)
        .join(
            sessions_subq,
            and_(
                sessions_subq.c.started_at < (buckets_subq.c.bucket_start + text("interval '1 hour'")),
                sessions_subq.c.ended_at > buckets_subq.c.bucket_start,
            ),
            isouter=True,
        )
        .join(Tag, Tag.id == sessions_subq.c.tag_id, isouter=True)
        .join(Person, Person.id == Tag.person_id, isouter=True)
        .group_by(hour_expr)
        .order_by(hour_expr)
    )

    res = await db.execute(stmt)
    rows = res.all()

    by_hour: Dict[int, Tuple[int, int, int]] = {
        int(r.hour): (int(r.total_dwell_seconds or 0), int(r.sessions_count or 0), int(r.unique_people_count or 0))
        for r in rows
        if r.hour is not None
    }

    buckets: List[GatewayTimeOfDayBucket] = []
    for h in range(24):
        td, sc, up = by_hour.get(h, (0, 0, 0))
        buckets.append(GatewayTimeOfDayBucket(hour=h, total_dwell_seconds=td, sessions_count=sc, unique_people_count=up))

    return GatewayTimeOfDayDistribution(
        device_id=device.id,
        device_name=device.name,
        from_ts=window.from_ts,
        to_ts=window.to_ts,
        buckets=buckets,
    )


@router.get("/gateways/{device_id}/occupancy", response_model=GatewayOccupancyReport)
async def get_gateway_occupancy(
    device_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24)
    from_w, to_w = _require_finite_window(window, detail="from_ts e to_ts são obrigatórios")

    sessions_subq = (
        select(
            PresenceSession.id.label("id"),
            PresenceSession.tag_id.label("tag_id"),
            PresenceSession.started_at.label("started_at"),
            PresenceSession.ended_at.label("ended_at"),
            PresenceSession.duration_seconds.label("duration_seconds"),
            Tag.person_id.label("person_id"),
        )
        .select_from(PresenceSession)
        .join(Tag, Tag.id == PresenceSession.tag_id, isouter=True)
        .where(PresenceSession.device_id == device_id)
        .where(PresenceSession.started_at <= to_w, PresenceSession.ended_at >= from_w)
    ).subquery("gw_sessions")

    buckets_subq = _hour_buckets_subq(TimeWindow(from_ts=from_w, to_ts=to_w))

    overlap = _bucket_overlap_seconds_hour(
        sess_start=sessions_subq.c.started_at,
        sess_end=sessions_subq.c.ended_at,
        bucket_start=buckets_subq.c.bucket_start,
    )

    stmt = (
        select(
            buckets_subq.c.bucket_start.label("bucket_start"),
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
            func.count(func.distinct(sessions_subq.c.id)).label("sessions_count"),
            func.count(func.distinct(sessions_subq.c.tag_id)).label("unique_tags_count"),
            func.count(func.distinct(sessions_subq.c.person_id)).label("unique_people_count"),
        )
        .select_from(buckets_subq)
        .join(
            sessions_subq,
            and_(
                sessions_subq.c.started_at < (buckets_subq.c.bucket_start + text("interval '1 hour'")),
                sessions_subq.c.ended_at > buckets_subq.c.bucket_start,
            ),
            isouter=True,
        )
        .group_by(buckets_subq.c.bucket_start)
        .order_by(buckets_subq.c.bucket_start)
    )

    res = await db.execute(stmt)
    rows = res.all()

    buckets: List[TimeBucket] = []
    peak: Optional[PeakBucket] = None

    for r in rows:
        b = TimeBucket(
            bucket_start=r.bucket_start,
            total_dwell_seconds=int(r.total_dwell_seconds or 0),
            sessions_count=int(r.sessions_count or 0),
            unique_tags_count=int(r.unique_tags_count or 0),
            unique_people_count=int(r.unique_people_count or 0),
        )
        buckets.append(b)
        if peak is None or b.unique_people_count > peak.unique_people_count:
            peak = PeakBucket(bucket_start=b.bucket_start, unique_people_count=b.unique_people_count)

    stats_stmt = select(
        func.avg(sessions_subq.c.duration_seconds).label("avg"),
        func.percentile_cont(0.5).within_group(sessions_subq.c.duration_seconds).label("p50"),
        func.percentile_cont(0.95).within_group(sessions_subq.c.duration_seconds).label("p95"),
    ).select_from(sessions_subq)

    stats_res = await db.execute(stats_stmt)
    stats = stats_res.one()

    return GatewayOccupancyReport(
        device_id=device.id,
        device_name=device.name,
        from_ts=from_w,
        to_ts=to_w,
        buckets=buckets,
        peak=peak,
        avg_dwell_seconds=float(stats.avg) if stats.avg is not None else None,
        p50_dwell_seconds=float(stats.p50) if stats.p50 is not None else None,
        p95_dwell_seconds=float(stats.p95) if stats.p95 is not None else None,
    )


@router.get("/gateways/{device_id}/concurrency", response_model=GatewayConcurrencyReport)
async def get_gateway_concurrency(
    device_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24)
    from_w, to_w = _require_finite_window(window, detail="from_ts e to_ts são obrigatórios")

    sess = (
        select(
            func.greatest(PresenceSession.started_at, from_w).label("s"),
            func.least(PresenceSession.ended_at, to_w).label("e"),
            Tag.person_id.label("person_id"),
        )
        .select_from(PresenceSession)
        .join(Tag, Tag.id == PresenceSession.tag_id, isouter=True)
        .where(PresenceSession.device_id == device_id)
        .where(PresenceSession.started_at <= to_w, PresenceSession.ended_at >= from_w)
        .where(Tag.person_id.is_not(None))
    ).subquery("sess")

    start_events = select(sess.c.s.label("ts"), literal(1).label("delta"))
    end_events = select(sess.c.e.label("ts"), literal(-1).label("delta"))

    events = union_all(start_events, end_events).subquery("events")

    ordered = (
        select(
            events.c.ts.label("ts"),
            func.sum(events.c.delta).over(order_by=(events.c.ts, events.c.delta.desc())).label("concurrency"),
        )
        .select_from(events)
    ).subquery("ordered")

    per_hour = (
        select(
            func.date_trunc("hour", ordered.c.ts).label("bucket_start"),
            func.max(ordered.c.concurrency).label("peak_concurrency"),
        )
        .select_from(ordered)
        .group_by(func.date_trunc("hour", ordered.c.ts))
    ).subquery("per_hour")

    buckets_subq = _hour_buckets_subq(TimeWindow(from_ts=from_w, to_ts=to_w))

    stmt = (
        select(
            buckets_subq.c.bucket_start.label("bucket_start"),
            func.coalesce(per_hour.c.peak_concurrency, 0).label("peak_concurrency"),
        )
        .select_from(buckets_subq)
        .join(per_hour, per_hour.c.bucket_start == buckets_subq.c.bucket_start, isouter=True)
        .order_by(buckets_subq.c.bucket_start)
    )

    res = await db.execute(stmt)
    rows = res.all()

    buckets = [
        ConcurrencyBucket(bucket_start=r.bucket_start, peak_concurrency_people=int(r.peak_concurrency or 0))
        for r in rows
    ]

    return GatewayConcurrencyReport(
        device_id=device.id,
        device_name=device.name,
        from_ts=from_w,
        to_ts=to_w,
        buckets=buckets,
    )


# ---------------------------------------------------------------------------
# Building reports
# ---------------------------------------------------------------------------


@router.get("/buildings/{building_id}/summary", response_model=BuildingSummaryReport)
async def get_building_summary(
    building_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    min_duration_seconds: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    building = await db.get(Building, building_id)
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24 * 30)

    base = (
        select(
            PresenceSession.id.label("id"),
            PresenceSession.device_id.label("device_id"),
            PresenceSession.tag_id.label("tag_id"),
            PresenceSession.started_at.label("started_at"),
            PresenceSession.ended_at.label("ended_at"),
            Tag.person_id.label("person_id"),
        )
        .select_from(PresenceSession)
        .join(Device, Device.id == PresenceSession.device_id)
        .join(FloorPlan, FloorPlan.id == Device.floor_plan_id, isouter=True)
        .join(Floor, Floor.id == FloorPlan.floor_id, isouter=True)
        .join(Building, Building.id == Floor.building_id, isouter=True)
        .join(Tag, Tag.id == PresenceSession.tag_id, isouter=True)
        .where(Building.id == building_id)
        .where(
            _presence_intersects_window(
                started_col=PresenceSession.started_at,
                ended_col=PresenceSession.ended_at,
                window=window,
            )
        )
    )

    if min_duration_seconds is not None:
        base = base.where(PresenceSession.duration_seconds >= min_duration_seconds)

    sessions_subq = base.subquery("building_sessions")

    overlap = _overlap_seconds_expr(
        started_col=sessions_subq.c.started_at,
        ended_col=sessions_subq.c.ended_at,
        window_from=window.from_ts,
        window_to=window.to_ts,
    )

    summary_stmt = select(
        func.count().label("total_sessions"),
        func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
        func.count(func.distinct(sessions_subq.c.tag_id)).label("unique_tags_count"),
        func.count(func.distinct(sessions_subq.c.person_id)).label("unique_people_count"),
        func.avg(overlap).label("avg_dwell_seconds"),
    ).select_from(sessions_subq)

    sres = await db.execute(summary_stmt)
    srow = sres.one()

    by_sessions_stmt = (
        select(
            sessions_subq.c.device_id,
            Device.name.label("device_name"),
            func.count().label("sessions_count"),
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
            func.count(func.distinct(sessions_subq.c.person_id)).label("unique_people_count"),
        )
        .select_from(sessions_subq)
        .join(Device, Device.id == sessions_subq.c.device_id, isouter=True)
        .group_by(sessions_subq.c.device_id, Device.name)
        .order_by(func.count().desc())
        .limit(10)
    )

    r1 = await db.execute(by_sessions_stmt)
    top_by_sessions = [
        BuildingSummaryItem(
            device_id=x.device_id,
            device_name=x.device_name,
            sessions_count=int(x.sessions_count or 0),
            total_dwell_seconds=int(x.total_dwell_seconds or 0),
            unique_people_count=int(x.unique_people_count or 0),
        )
        for x in r1.all()
    ]

    by_dwell_stmt = by_sessions_stmt.order_by(func.coalesce(func.sum(overlap), 0).desc())
    r2 = await db.execute(by_dwell_stmt)
    top_by_dwell = [
        BuildingSummaryItem(
            device_id=x.device_id,
            device_name=x.device_name,
            sessions_count=int(x.sessions_count or 0),
            total_dwell_seconds=int(x.total_dwell_seconds or 0),
            unique_people_count=int(x.unique_people_count or 0),
        )
        for x in r2.all()
    ]

    return BuildingSummaryReport(
        building_id=building.id,
        building_name=building.name,
        from_ts=window.from_ts,
        to_ts=window.to_ts,
        total_sessions=int(srow.total_sessions or 0),
        total_dwell_seconds=int(srow.total_dwell_seconds or 0),
        unique_people_count=int(srow.unique_people_count or 0),
        unique_tags_count=int(srow.unique_tags_count or 0),
        avg_dwell_seconds=float(srow.avg_dwell_seconds or 0.0) if srow.avg_dwell_seconds is not None else None,
        top_gateways_by_sessions=top_by_sessions,
        top_gateways_by_dwell=top_by_dwell,
    )


@router.get("/buildings/{building_id}/time-of-day", response_model=List[TimeBucket])
async def get_building_time_of_day(
    building_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    building = await db.get(Building, building_id)
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24)
    from_w, to_w = _require_finite_window(window, detail="from_ts e to_ts são obrigatórios")

    sessions_subq = (
        select(
            PresenceSession.id.label("id"),
            PresenceSession.tag_id.label("tag_id"),
            PresenceSession.started_at.label("started_at"),
            PresenceSession.ended_at.label("ended_at"),
            Tag.person_id.label("person_id"),
        )
        .select_from(PresenceSession)
        .join(Device, Device.id == PresenceSession.device_id)
        .join(FloorPlan, FloorPlan.id == Device.floor_plan_id, isouter=True)
        .join(Floor, Floor.id == FloorPlan.floor_id, isouter=True)
        .join(Building, Building.id == Floor.building_id, isouter=True)
        .join(Tag, Tag.id == PresenceSession.tag_id, isouter=True)
        .where(Building.id == building_id)
        .where(PresenceSession.started_at <= to_w, PresenceSession.ended_at >= from_w)
    ).subquery("b_sessions")

    buckets_subq = _hour_buckets_subq(TimeWindow(from_ts=from_w, to_ts=to_w))
    overlap = _bucket_overlap_seconds_hour(
        sess_start=sessions_subq.c.started_at,
        sess_end=sessions_subq.c.ended_at,
        bucket_start=buckets_subq.c.bucket_start,
    )

    stmt = (
        select(
            buckets_subq.c.bucket_start,
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
            func.count(func.distinct(sessions_subq.c.id)).label("sessions_count"),
            func.count(func.distinct(sessions_subq.c.tag_id)).label("unique_tags_count"),
            func.count(func.distinct(sessions_subq.c.person_id)).label("unique_people_count"),
        )
        .select_from(buckets_subq)
        .join(
            sessions_subq,
            and_(
                sessions_subq.c.started_at < (buckets_subq.c.bucket_start + text("interval '1 hour'")),
                sessions_subq.c.ended_at > buckets_subq.c.bucket_start,
            ),
            isouter=True,
        )
        .group_by(buckets_subq.c.bucket_start)
        .order_by(buckets_subq.c.bucket_start)
    )

    res = await db.execute(stmt)
    rows = res.all()

    return [
        TimeBucket(
            bucket_start=r.bucket_start,
            total_dwell_seconds=int(r.total_dwell_seconds or 0),
            sessions_count=int(r.sessions_count or 0),
            unique_tags_count=int(r.unique_tags_count or 0),
            unique_people_count=int(r.unique_people_count or 0),
        )
        for r in rows
    ]


@router.get("/buildings/{building_id}/time-distribution/calendar", response_model=List[TimeBucket])
async def get_building_time_distribution_calendar(
    building_id: int,
    granularity: Literal["day", "week", "month", "year"] = Query(default="day"),
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    building = await db.get(Building, building_id)
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24 * 30)
    from_w, to_w = _require_finite_window(window, detail="from_ts e to_ts são obrigatórios")

    step_sql = _calendar_step_interval(granularity)

    sessions_subq = (
        select(
            PresenceSession.id.label("id"),
            PresenceSession.tag_id.label("tag_id"),
            PresenceSession.started_at.label("started_at"),
            PresenceSession.ended_at.label("ended_at"),
            Tag.person_id.label("person_id"),
        )
        .select_from(PresenceSession)
        .join(Device, Device.id == PresenceSession.device_id)
        .join(FloorPlan, FloorPlan.id == Device.floor_plan_id, isouter=True)
        .join(Floor, Floor.id == FloorPlan.floor_id, isouter=True)
        .join(Building, Building.id == Floor.building_id, isouter=True)
        .join(Tag, Tag.id == PresenceSession.tag_id, isouter=True)
        .where(Building.id == building_id)
        .where(PresenceSession.started_at <= to_w, PresenceSession.ended_at >= from_w)
    ).subquery("b_cal_sessions")

    buckets_subq = _calendar_buckets_subq(TimeWindow(from_ts=from_w, to_ts=to_w), granularity)

    overlap = _bucket_overlap_seconds_generic(
        sess_start=sessions_subq.c.started_at,
        sess_end=sessions_subq.c.ended_at,
        bucket_start=buckets_subq.c.bucket_start,
        step_interval_sql=step_sql,
    )

    stmt = (
        select(
            buckets_subq.c.bucket_start,
            func.coalesce(func.sum(overlap), 0).label("total_dwell_seconds"),
            func.count(func.distinct(sessions_subq.c.id)).label("sessions_count"),
            func.count(func.distinct(sessions_subq.c.tag_id)).label("unique_tags_count"),
            func.count(func.distinct(sessions_subq.c.person_id)).label("unique_people_count"),
        )
        .select_from(buckets_subq)
        .join(
            sessions_subq,
            and_(
                sessions_subq.c.started_at < (buckets_subq.c.bucket_start + text(step_sql)),
                sessions_subq.c.ended_at > buckets_subq.c.bucket_start,
            ),
            isouter=True,
        )
        .group_by(buckets_subq.c.bucket_start)
        .order_by(buckets_subq.c.bucket_start)
    )

    res = await db.execute(stmt)
    rows = res.all()

    return [
        TimeBucket(
            bucket_start=r.bucket_start,
            total_dwell_seconds=int(r.total_dwell_seconds or 0),
            sessions_count=int(r.sessions_count or 0),
            unique_tags_count=int(r.unique_tags_count or 0),
            unique_people_count=int(r.unique_people_count or 0),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Alerts summaries by scope
# ---------------------------------------------------------------------------


@router.get("/gateways/{device_id}/alerts/summary", response_model=AlertsSummaryReport)
async def get_gateway_alerts_summary(
    device_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24 * 30)

    filters = [AlertEvent.device_id == device_id]
    if window.from_ts is not None:
        filters.append(AlertEvent.started_at >= window.from_ts)
    if window.to_ts is not None:
        filters.append(AlertEvent.started_at <= window.to_ts)

    stmt = (
        select(AlertEvent.event_type.label("event_type"), func.count().label("alerts_count"))
        .where(*filters)
        .group_by(AlertEvent.event_type)
        .order_by(func.count().desc())
    )

    res = await db.execute(stmt)
    rows = res.all()
    total = sum(int(r.alerts_count or 0) for r in rows)

    return AlertsSummaryReport(
        scope="gateway",
        scope_id=device_id,
        from_ts=window.from_ts,
        to_ts=window.to_ts,
        total_alerts=total,
        by_type=[AlertTypeCount(event_type=r.event_type or "UNKNOWN", alerts_count=int(r.alerts_count or 0)) for r in rows],
    )


@router.get("/buildings/{building_id}/alerts/summary", response_model=AlertsSummaryReport)
async def get_building_alerts_summary(
    building_id: int,
    from_ts: Optional[datetime] = Query(default=None),
    to_ts: Optional[datetime] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    building = await db.get(Building, building_id)
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    window = _coerce_window(from_ts=from_ts, to_ts=to_ts, default_hours=24 * 30)

    filters = [Building.id == building_id]
    if window.from_ts is not None:
        filters.append(AlertEvent.started_at >= window.from_ts)
    if window.to_ts is not None:
        filters.append(AlertEvent.started_at <= window.to_ts)

    stmt = (
        select(AlertEvent.event_type.label("event_type"), func.count().label("alerts_count"))
        .select_from(AlertEvent)
        .join(Device, Device.id == AlertEvent.device_id, isouter=True)
        .join(FloorPlan, FloorPlan.id == Device.floor_plan_id, isouter=True)
        .join(Floor, Floor.id == FloorPlan.floor_id, isouter=True)
        .join(Building, Building.id == Floor.building_id, isouter=True)
        .where(*filters)
        .group_by(AlertEvent.event_type)
        .order_by(func.count().desc())
    )

    res = await db.execute(stmt)
    rows = res.all()
    total = sum(int(r.alerts_count or 0) for r in rows)

    return AlertsSummaryReport(
        scope="building",
        scope_id=building_id,
        from_ts=window.from_ts,
        to_ts=window.to_ts,
        total_alerts=total,
        by_type=[AlertTypeCount(event_type=r.event_type or "UNKNOWN", alerts_count=int(r.alerts_count or 0)) for r in rows],
    )
