# app/api/routes/positions.py
from datetime import datetime
from typing import Dict, List, Tuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.models import (
    Person,
    Tag,
    Device,
    FloorPlan,
    Floor,
    Building,
)
from app.models.person_group import person_group_memberships
from app.models.collection_log import CollectionLog
from app.schemas.location import PersonCurrentLocation, DeviceCurrentOccupancy

router = APIRouter()


async def _load_current_positions(
    db: AsyncSession,
    *,
    building_id: int | None,
    floor_id: int | None,
    floor_plan_id: int | None,
    device_id: int | None,
    group_id: int | None,
    only_active_people: bool,
) -> List[PersonCurrentLocation]:
    """
    Carrega a posição atual (última leitura) de todas as pessoas,
    aplicando filtros opcionais.
    """

    # Subquery: última leitura por TAG
    latest_per_tag = (
        select(
            CollectionLog.tag_id.label("tag_id"),
            func.max(CollectionLog.created_at).label("last_seen_at"),
        )
        .group_by(CollectionLog.tag_id)
        .subquery()
    )

    # Query base:
    # Tag -> Person -> latest_per_tag -> CollectionLog -> Device -> FloorPlan -> Floor -> Building
    stmt = (
        select(
            Person,
            Tag,
            Device,
            FloorPlan,
            Floor,
            Building,
            CollectionLog.created_at.label("seen_at"),
        )
        .join(Tag, Tag.person_id == Person.id)
        .join(latest_per_tag, latest_per_tag.c.tag_id == Tag.id)
        .join(
            CollectionLog,
            (CollectionLog.tag_id == Tag.id)
            & (CollectionLog.created_at == latest_per_tag.c.last_seen_at),
        )
        .join(Device, Device.id == CollectionLog.device_id)
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
        stmt = stmt.join(
            person_group_memberships,
            person_group_memberships.c.person_id == Person.id,
        ).where(person_group_memberships.c.group_id == group_id)

    result = await db.execute(stmt)
    rows: List[
        Tuple[Person, Tag, Device, FloorPlan | None, Floor | None, Building | None, datetime]
    ] = result.all()

    # pode haver múltiplas TAGs por pessoa; escolhemos a leitura mais recente por pessoa
    best_by_person: Dict[
        int,
        Tuple[Person, Tag, Device, FloorPlan | None, Floor | None, Building | None, datetime],
    ] = {}

    for person, tag, device, fp, fl, bld, seen_at in rows:
        current = best_by_person.get(person.id)
        if current is None or seen_at > current[6]:
            best_by_person[person.id] = (person, tag, device, fp, fl, bld, seen_at)

    locations: List[PersonCurrentLocation] = []

    for (
        _pid,
        (person, tag, device, fp, fl, bld, seen_at),
    ) in best_by_person.items():
        # se o gateway ainda não está posicionado numa planta, você pode optar por pular
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

    return locations


@router.get("/current", response_model=List[PersonCurrentLocation])
async def list_current_positions(
    building_id: int | None = Query(default=None),
    floor_id: int | None = Query(default=None),
    floor_plan_id: int | None = Query(default=None),
    device_id: int | None = Query(default=None),
    group_id: int | None = Query(default=None),
    only_active_people: bool = True,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Lista a posição atual de cada pessoa (uma linha por pessoa),
    com filtros por prédio/andar/planta/device/grupo.
    """
    return await _load_current_positions(
        db=db,
        building_id=building_id,
        floor_id=floor_id,
        floor_plan_id=floor_plan_id,
        device_id=device_id,
        group_id=group_id,
        only_active_people=only_active_people,
    )


@router.get("/by-device", response_model=List[DeviceCurrentOccupancy])
async def list_positions_by_device(
    building_id: int | None = Query(default=None),
    floor_id: int | None = Query(default=None),
    floor_plan_id: int | None = Query(default=None),
    device_id: int | None = Query(default=None),
    group_id: int | None = Query(default=None),
    only_active_people: bool = True,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Retorna a ocupação atual POR GATEWAY (device):

    [
      {
        device_id,
        device_name,
        ...infos do setor/planta...,
        people: [ PersonCurrentLocation, ... ]
      },
      ...
    ]
    """

    locations = await _load_current_positions(
        db=db,
        building_id=building_id,
        floor_id=floor_id,
        floor_plan_id=floor_plan_id,
        device_id=device_id,
        group_id=group_id,
        only_active_people=only_active_people,
    )

    occupancy_map: Dict[int, DeviceCurrentOccupancy] = {}

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

    return list(occupancy_map.values())
