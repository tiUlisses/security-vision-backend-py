# app/api/routes/positions.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.config import settings
from app.models import (
    Person,
    Tag,
    Device,
    FloorPlan,
    Floor,
    Building,
)
from app.models.collection_log import CollectionLog
from app.models.person_group import person_group_memberships
from app.schemas.location import PersonCurrentLocation, DeviceCurrentOccupancy

router = APIRouter()


def _resolve_cutoff(max_age_seconds: int | None) -> tuple[int, datetime | None]:
    """
    Resolve a janela de tempo para considerar presença.

    Regras:
      - max_age_seconds=None  -> usa settings.POSITION_STALE_THRESHOLD_SECONDS (default 30)
      - max_age_seconds=0     -> desabilita expiração (cutoff=None)
      - max_age_seconds>0     -> expira (cutoff = utcnow - max_age_seconds)
    """
    if max_age_seconds is None:
        max_age_seconds = getattr(settings, "POSITION_STALE_THRESHOLD_SECONDS", 30)

    if not max_age_seconds or max_age_seconds <= 0:
        return 0, None

    return int(max_age_seconds), datetime.utcnow() - timedelta(seconds=int(max_age_seconds))


def _latest_log_per_tag_subquery(cutoff: datetime | None):
    """
    Subquery determinística do último CollectionLog por TAG.

    Usa window function:
        row_number() over(partition by tag_id order by created_at desc, id desc)

    Assim evita:
      - empates quando dois logs têm o mesmo created_at
      - join por max(created_at) que pode retornar múltiplas linhas
    """
    logs_stmt = select(
        CollectionLog.id.label("log_id"),
        CollectionLog.tag_id.label("tag_id"),
        CollectionLog.device_id.label("device_id"),
        CollectionLog.created_at.label("seen_at"),
        func.row_number()
        .over(
            partition_by=CollectionLog.tag_id,
            order_by=(CollectionLog.created_at.desc(), CollectionLog.id.desc()),
        )
        .label("rn"),
    )

    if cutoff is not None:
        logs_stmt = logs_stmt.where(CollectionLog.created_at >= cutoff)

    return logs_stmt.subquery("latest_logs_ranked")


async def _load_current_positions(
    db: AsyncSession,
    *,
    building_id: int | None,
    floor_id: int | None,
    floor_plan_id: int | None,
    device_id: int | None,
    group_id: int | None,
    only_active_people: bool,
    max_age_seconds: int | None,
) -> List[PersonCurrentLocation]:
    """
    Retorna a posição atual (última leitura dentro da janela) de cada pessoa.

    Observações importantes:
    - A presença é baseada na última leitura de qualquer TAG associada à pessoa.
    - Se o gateway não estiver posicionado em uma FloorPlan (floor_plan_id), ele não entra
      no retorno porque PersonCurrentLocation exige floor_plan/floor/building não-nulos.
    """

    _ttl, cutoff = _resolve_cutoff(max_age_seconds)
    latest_logs = _latest_log_per_tag_subquery(cutoff)

    # Query base:
    # Person -> Tag -> latest_logs(rn=1) -> Device -> FloorPlan -> Floor -> Building
    #
    # Importante:
    # - Mantemos floor_plan como referência espacial principal (contrato atual do schema).
    stmt = (
        select(
            Person,
            Tag,
            Device,
            FloorPlan,
            Floor,
            Building,
            latest_logs.c.seen_at.label("seen_at"),
        )
        .join(Tag, Tag.person_id == Person.id)
        .join(latest_logs, (latest_logs.c.tag_id == Tag.id) & (latest_logs.c.rn == 1))
        .join(Device, Device.id == latest_logs.c.device_id)
        .outerjoin(FloorPlan, Device.floor_plan_id == FloorPlan.id)
        .outerjoin(Floor, FloorPlan.floor_id == Floor.id)
        .outerjoin(Building, Floor.building_id == Building.id)
    )

    if only_active_people:
        stmt = stmt.where(Person.active.is_(True))

    if device_id is not None:
        stmt = stmt.where(Device.id == device_id)
    if floor_plan_id is not None:
        stmt = stmt.where(FloorPlan.id == floor_plan_id)
    if floor_id is not None:
        stmt = stmt.where(Floor.id == floor_id)
    if building_id is not None:
        stmt = stmt.where(Building.id == building_id)

    if group_id is not None:
        stmt = (
            stmt.join(
                person_group_memberships,
                person_group_memberships.c.person_id == Person.id,
            )
            .where(person_group_memberships.c.group_id == group_id)
        )

    result = await db.execute(stmt)

    rows: List[
        Tuple[
            Person,
            Tag,
            Device,
            FloorPlan | None,
            Floor | None,
            Building | None,
            datetime,
        ]
    ] = result.all()

    # Pode haver múltiplas TAGs por pessoa; escolhemos a leitura mais recente por pessoa.
    best_by_person: Dict[
        int,
        Tuple[Person, Tag, Device, FloorPlan | None, Floor | None, Building | None, datetime],
    ] = {}

    for person, tag, device, fp, fl, bld, seen_at in rows:
        cur = best_by_person.get(person.id)
        if cur is None or seen_at > cur[6]:
            best_by_person[person.id] = (person, tag, device, fp, fl, bld, seen_at)

    locations: List[PersonCurrentLocation] = []

    for _pid, (person, tag, device, fp, fl, bld, seen_at) in best_by_person.items():
        # Contrato atual exige que exista floor_plan/floor/building.
        if not fp or not fl or not bld:
            continue

        locations.append(
            PersonCurrentLocation(
                person_id=person.id,
                person_full_name=person.full_name,
                tag_id=tag.id,
                tag_mac_address=tag.mac_address,
                device_id=device.id,
                device_name=device.name,
                device_mac_address=device.mac_address,
                device_pos_x=device.pos_x,
                device_pos_y=device.pos_y,
                floor_plan_id=fp.id,
                floor_plan_name=fp.name,
                floor_plan_image_url=fp.image_url,
                floor_id=fl.id,
                floor_name=fl.name,
                building_id=bld.id,
                building_name=bld.name,
                last_seen_at=seen_at,
            )
        )

    # Ordena para retorno estável (opcional)
    locations.sort(key=lambda x: (x.building_id, x.floor_plan_id, x.device_id, x.person_full_name))
    return locations


@router.get("/current", response_model=List[PersonCurrentLocation])
async def list_current_positions(
    building_id: int | None = Query(default=None),
    floor_id: int | None = Query(default=None),
    floor_plan_id: int | None = Query(default=None),
    device_id: int | None = Query(default=None),
    group_id: int | None = Query(default=None),
    only_active_people: bool = True,
    max_age_seconds: int | None = Query(default=None, ge=0, le=86400),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Lista a posição atual de cada pessoa (uma linha por pessoa),
    com filtros por prédio/andar/planta/device/grupo.

    max_age_seconds:
      - None: usa default do settings (POSITION_STALE_THRESHOLD_SECONDS)
      - 0: desabilita expiração
      - >0: TTL em segundos
    """
    return await _load_current_positions(
        db=db,
        building_id=building_id,
        floor_id=floor_id,
        floor_plan_id=floor_plan_id,
        device_id=device_id,
        group_id=group_id,
        only_active_people=only_active_people,
        max_age_seconds=max_age_seconds,
    )


@router.get("/by-device", response_model=List[DeviceCurrentOccupancy])
async def list_positions_by_device(
    building_id: int | None = Query(default=None),
    floor_id: int | None = Query(default=None),
    floor_plan_id: int | None = Query(default=None),
    device_id: int | None = Query(default=None),
    group_id: int | None = Query(default=None),
    only_active_people: bool = True,
    max_age_seconds: int | None = Query(default=None, ge=0, le=86400),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Retorna a ocupação atual POR GATEWAY (device).

    max_age_seconds:
      - None: usa default do settings (POSITION_STALE_THRESHOLD_SECONDS)
      - 0: desabilita expiração
      - >0: TTL em segundos
    """
    locations = await _load_current_positions(
        db=db,
        building_id=building_id,
        floor_id=floor_id,
        floor_plan_id=floor_plan_id,
        device_id=device_id,
        group_id=group_id,
        only_active_people=only_active_people,
        max_age_seconds=max_age_seconds,
    )

    occupancy_map: Dict[int, DeviceCurrentOccupancy] = {}

    # Agrupa por device
    for loc in locations:
        dev_id = loc.device_id
        occ = occupancy_map.get(dev_id)
        if occ is None:
            occ = DeviceCurrentOccupancy(
                device_id=loc.device_id,
                device_name=loc.device_name,
                device_mac_address=loc.device_mac_address,
                device_pos_x=loc.device_pos_x,
                device_pos_y=loc.device_pos_y,
                floor_plan_id=loc.floor_plan_id,
                floor_plan_name=loc.floor_plan_name,
                floor_plan_image_url=loc.floor_plan_image_url,
                floor_id=loc.floor_id,
                floor_name=loc.floor_name,
                building_id=loc.building_id,
                building_name=loc.building_name,
                people=[],
            )
            occupancy_map[dev_id] = occ

        occ.people.append(loc)

    # Ordenação estável: devices por nome; pessoas por last_seen_at desc
    result = list(occupancy_map.values())
    for occ in result:
        occ.people.sort(key=lambda p: p.last_seen_at, reverse=True)
    result.sort(key=lambda o: (o.building_id or 0, o.floor_plan_id or 0, o.device_name or ""))

    return result
