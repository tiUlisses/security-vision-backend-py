# app/schemas/person_report.py
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class PersonDwellByDevice(BaseModel):
    device_id: int
    device_name: Optional[str] = None

    building_id: Optional[int] = None
    building_name: Optional[str] = None

    floor_id: Optional[int] = None
    floor_name: Optional[str] = None

    floor_plan_id: Optional[int] = None
    floor_plan_name: Optional[str] = None

    total_dwell_seconds: int
    sessions_count: int


class PersonPresenceSummary(BaseModel):
    person_id: int
    person_full_name: str

    from_ts: Optional[datetime] = None
    to_ts: Optional[datetime] = None

    total_dwell_seconds: int
    total_sessions: int

    first_session_at: Optional[datetime] = None
    last_session_at: Optional[datetime] = None

    dwell_by_device: List[PersonDwellByDevice]

    # atalho: device onde mais ficou
    top_device_id: Optional[int] = None


class PersonTimelineSession(BaseModel):
    session_id: int

    device_id: int
    device_name: Optional[str] = None

    building_id: Optional[int] = None
    building_name: Optional[str] = None

    floor_id: Optional[int] = None
    floor_name: Optional[str] = None

    floor_plan_id: Optional[int] = None
    floor_plan_name: Optional[str] = None

    tag_id: int

    started_at: datetime
    ended_at: datetime
    duration_seconds: int
    samples_count: int

# =========================
# ALERTAS POR PESSOA (Patch 2)
# =========================
class PersonAlertByType(BaseModel):
    event_type: str
    alerts_count: int


class PersonAlertByDevice(BaseModel):
    device_id: Optional[int] = None
    device_name: Optional[str] = None

    building_id: Optional[int] = None
    building_name: Optional[str] = None

    floor_id: Optional[int] = None
    floor_name: Optional[str] = None

    alerts_count: int


class PersonAlertEvent(BaseModel):
    id: int
    event_type: str

    device_id: Optional[int] = None
    device_name: Optional[str] = None

    building_id: Optional[int] = None
    building_name: Optional[str] = None

    floor_id: Optional[int] = None
    floor_name: Optional[str] = None

    floor_plan_id: Optional[int] = None
    floor_plan_name: Optional[str] = None

    tag_id: Optional[int] = None

    started_at: datetime
    ended_at: Optional[datetime] = None


class PersonAlertsReport(BaseModel):
    person_id: int
    person_full_name: str

    from_ts: Optional[datetime] = None
    to_ts: Optional[datetime] = None

    total_alerts: int
    first_alert_at: Optional[datetime] = None
    last_alert_at: Optional[datetime] = None

    by_type: List[PersonAlertByType]
    by_device: List[PersonAlertByDevice]
    events: List[PersonAlertEvent]


class PersonTimeDistributionBucket(BaseModel):
    """
    Bucket de tempo "calendário": dia, semana, mês, ano.
    """
    bucket_start: datetime        # início do bucket (ex: 2025-11-01)
    total_dwell_seconds: int
    sessions_count: int


class PersonTimeDistributionCalendar(BaseModel):
    """
    Distribuição de tempo por dia/semana/mês/ano.
    """
    person_id: int
    person_full_name: str

    from_ts: Optional[datetime] = None
    to_ts: Optional[datetime] = None

    granularity: str             # "day" | "week" | "month" | "year"
    buckets: List[PersonTimeDistributionBucket]


class PersonTimeOfDayBucket(BaseModel):
    """
    Distribuição por hora do dia (0–23).
    """
    hour: int                    # 0..23
    total_dwell_seconds: int
    sessions_count: int


class PersonTimeOfDayDistribution(BaseModel):
    person_id: int
    person_full_name: str
    from_ts: Optional[datetime] = None
    to_ts: Optional[datetime] = None
    buckets: List[PersonTimeOfDayBucket]


class PersonDayOfWeekBucket(BaseModel):
    """
    Distribuição por dia da semana (0..6) – padrão PostgreSQL:
    0 = domingo, 1 = segunda, ..., 6 = sábado
    """
    day_of_week: int             # 0..6
    total_dwell_seconds: int
    sessions_count: int


class PersonDayOfWeekDistribution(BaseModel):
    person_id: int
    person_full_name: str
    from_ts: Optional[datetime] = None
    to_ts: Optional[datetime] = None
    buckets: List[PersonDayOfWeekBucket]

class GroupPersonDwellSummary(BaseModel):
    """Resumo de tempo por pessoa dentro de um grupo."""
    person_id: int
    person_full_name: str
    total_dwell_seconds: int
    sessions_count: int


class GroupDwellByDevice(BaseModel):
    """Resumo de tempo por device (gateway) agregando todo o grupo."""
    device_id: int
    device_name: Optional[str] = None

    building_id: Optional[int] = None
    building_name: Optional[str] = None

    floor_id: Optional[int] = None
    floor_name: Optional[str] = None

    floor_plan_id: Optional[int] = None
    floor_plan_name: Optional[str] = None

    total_dwell_seconds: int
    sessions_count: int
    unique_people_count: int


class PersonGroupPresenceSummary(BaseModel):
    """Resumo de presença de um grupo de pessoas."""
    group_id: int
    group_name: str

    from_ts: Optional[datetime] = None
    to_ts: Optional[datetime] = None

    total_dwell_seconds: int
    total_sessions: int
    total_unique_people: int

    first_session_at: Optional[datetime] = None
    last_session_at: Optional[datetime] = None

    dwell_by_device: List[GroupDwellByDevice]
    dwell_by_person: List[GroupPersonDwellSummary]

    top_device_id: Optional[int] = None


class PersonGroupAlertsReport(BaseModel):
    """Relatório de alertas de um grupo de pessoas."""
    group_id: int
    group_name: str

    from_ts: Optional[datetime] = None
    to_ts: Optional[datetime] = None

    total_alerts: int
    first_alert_at: Optional[datetime] = None
    last_alert_at: Optional[datetime] = None

    # podemos reutilizar os schemas já existentes
    by_type: List[PersonAlertByType]
    by_device: List[PersonAlertByDevice]
    events: List[PersonAlertEvent]

class PersonHourByGatewayBucket(BaseModel):
    """
    Um bucket representa uma combinação (hora do dia, gateway).
    Ex:
      - hour = 10
      - device_id = 5
      - total_dwell_seconds = 600  (10 minutos)
      - sessions_count = 3
    """
    hour: int
    device_id: int
    device_name: Optional[str] = None
    total_dwell_seconds: int
    sessions_count: int


class PersonTimeOfDayByGateway(BaseModel):
    """
    Resumo para a pessoa ao longo das 24h,
    quebrado por gateway e hora.
    """
    person_id: int
    person_full_name: str
    from_ts: Optional[datetime]
    to_ts: Optional[datetime]
    buckets: List[PersonHourByGatewayBucket]


class PresenceTransitionReportItem(BaseModel):
    tag_id: int
    tag_label: Optional[str] = None

    person_id: Optional[int] = None
    person_full_name: Optional[str] = None

    from_device_id: int
    from_device_name: Optional[str] = None

    to_device_id: int
    to_device_name: Optional[str] = None

    transition_start_at: datetime
    transition_end_at: datetime
    transition_seconds: int
