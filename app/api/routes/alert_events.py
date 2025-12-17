# app/api/routes/alert_events.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.models.alert_event import AlertEvent
from app.schemas.alert_event import AlertEventRead

router = APIRouter()


@router.get("/", response_model=List[AlertEventRead])
async def list_alert_events(
    skip: int = 0,
    limit: int = 20,
    event_type: Optional[str] = Query(default=None),
    device_id: Optional[int] = Query(default=None),
    person_id: Optional[int] = Query(default=None),
    tag_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    stmt = select(AlertEvent)

    if event_type:
        stmt = stmt.where(AlertEvent.event_type == event_type)

    if device_id is not None:
        stmt = stmt.where(AlertEvent.device_id == device_id)

    if person_id is not None:
        stmt = stmt.where(AlertEvent.person_id == person_id)

    if tag_id is not None:
        stmt = stmt.where(AlertEvent.tag_id == tag_id)

    stmt = (
        stmt.order_by(AlertEvent.started_at.desc())
        .offset(skip)
        .limit(limit)
    )

    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{event_id}", response_model=AlertEventRead)
async def get_alert_event(
    event_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    stmt = select(AlertEvent).where(AlertEvent.id == event_id)
    result = await db.execute(stmt)
    event = result.scalar_one_or_none()

    if not event:
        raise HTTPException(status_code=404, detail="Alert event not found")

    return event
