from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.config import settings
from app.models.person import Person
from app.models.tag import Tag
from app.models.device import Device
from app.models.alert_rule import AlertRule
from app.models.alert_event import AlertEvent
from app.schemas.dashboard import DashboardSummary

router = APIRouter()


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    db: AsyncSession = Depends(get_db_session),
):
    total_people = await db.scalar(select(func.count(Person.id)))
    total_tags = await db.scalar(select(func.count(Tag.id)))
    total_gateways = await db.scalar(
        select(func.count(Device.id)).where(Device.type == "BLE_GATEWAY")
    )

    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=settings.DEVICE_OFFLINE_THRESHOLD_SECONDS)

    gateways_online = await db.scalar(
        select(func.count(Device.id)).where(
            Device.type == "BLE_GATEWAY",
            Device.last_seen_at.is_not(None),
            Device.last_seen_at >= cutoff,
        )
    )

    gateways_online = gateways_online or 0
    total_gateways = total_gateways or 0
    gateways_offline = max(total_gateways - gateways_online, 0)

    active_alert_rules = await db.scalar(
        select(func.count(AlertRule.id)).where(AlertRule.is_active.is_(True))
    ) or 0

    recent_alerts_24h = await db.scalar(
        select(func.count(AlertEvent.id)).where(
            AlertEvent.triggered_at >= now - timedelta(hours=24)
        )
    ) or 0

    return DashboardSummary(
        total_people=total_people or 0,
        total_tags=total_tags or 0,
        total_gateways=total_gateways,
        gateways_online=gateways_online,
        gateways_offline=gateways_offline,
        active_alert_rules=active_alert_rules,
        recent_alerts_24h=recent_alerts_24h,
    )
