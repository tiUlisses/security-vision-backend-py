from __future__ import annotations

"""
Serviço de projeção para o vision-controller.

- Origem do "ambiente":
  - Location -> app/models/location.py (registro local já existe).
  - FloorPlan -> app/models/floor_plan.py (não cria Location adicional).
"""

import json
import logging
from typing import Optional

from asyncio_mqtt import Client as MQTTClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.building import Building
from app.models.floor import Floor
from app.models.floor_plan import FloorPlan
from app.models.location import Location

logger = logging.getLogger(__name__)


def _build_display_name(building_name: str, floor_name: str, environment_name: str) -> str:
    return f"{building_name} - {floor_name} - {environment_name}"


async def _publish_projection(payload: dict) -> None:
    if not settings.ACCESS_CONTROL_MQTT_ENABLED:
        logger.debug(
            "[access-control] ACCESS_CONTROL_MQTT_ENABLED=false, não publicando payload=%s",
            payload,
        )
        return
    if not settings.RTLS_MQTT_ENABLED:
        logger.debug(
            "[access-control] RTLS_MQTT_ENABLED=false, não publicando payload=%s",
            payload,
        )
        return

    topic = settings.ACCESS_CONTROL_MQTT_TOPIC.rstrip("/")
    host = settings.RTLS_MQTT_HOST
    port = settings.RTLS_MQTT_PORT
    username = settings.RTLS_MQTT_USERNAME or None
    password = settings.RTLS_MQTT_PASSWORD or None

    payload_str = json.dumps(payload, ensure_ascii=False)
    logger.info(
        "[access-control] MQTT publish topic=%s payload=%s",
        topic,
        payload_str,
    )

    async with MQTTClient(
        hostname=host,
        port=port,
        username=username,
        password=password,
    ) as client:
        await client.publish(topic, payload_str, qos=1, retain=True)


async def _choose_floor_for_location(
    db: AsyncSession,
    location: Location,
    building_id: int | None = None,
) -> Floor | None:
    await db.refresh(location, attribute_names=["floors"])
    floors = location.floors or []
    if building_id is not None:
        floors = [floor for floor in floors if floor.building_id == building_id]
    if not floors:
        return None
    return sorted(floors, key=lambda floor: floor.id)[0]


async def build_projection_from_location(
    db: AsyncSession,
    location: Location,
    *,
    building_id: int | None = None,
) -> Optional[dict]:
    """
    Monta payload de projeção para o vision-controller baseado em Location.

    location_id:
      - deriva de Location.id (ID interno persistido) para garantir estabilidade
        nas atualizações e referências do access-control.
    """
    floor = await _choose_floor_for_location(db, location, building_id=building_id)
    if not floor:
        logger.warning(
            "[access-control] Location %s sem floor associado, projeção ignorada",
            location.id,
        )
        return None
    await db.refresh(floor, attribute_names=["building"])
    building = floor.building
    if not building:
        logger.warning(
            "[access-control] Floor %s sem building associado, projeção ignorada",
            floor.id,
        )
        return None

    name = _build_display_name(building.name, floor.name, location.name)
    return {
        "location_id": location.id,
        "name": name,
        "source": "location",
        "source_id": location.id,
        "building_id": building.id,
        "building_name": building.name,
        "floor_id": floor.id,
        "floor_name": floor.name,
    }


async def build_projection_from_floor_plan(
    db: AsyncSession,
    floor_plan: FloorPlan,
) -> Optional[dict]:
    """
    Monta payload de projeção para o vision-controller baseado em FloorPlan.

    location_id:
      - deriva de FloorPlan.id quando o "ambiente" é uma planta.
    """
    await db.refresh(floor_plan, attribute_names=["floor"])
    floor = floor_plan.floor
    if not floor:
        logger.warning(
            "[access-control] FloorPlan %s sem floor associado, projeção ignorada",
            floor_plan.id,
        )
        return None
    await db.refresh(floor, attribute_names=["building"])
    building = floor.building
    if not building:
        logger.warning(
            "[access-control] Floor %s sem building associado, projeção ignorada",
            floor.id,
        )
        return None

    name = _build_display_name(building.name, floor.name, floor_plan.name)
    return {
        "location_id": floor_plan.id,
        "name": name,
        "source": "floor_plan",
        "source_id": floor_plan.id,
        "building_id": building.id,
        "building_name": building.name,
        "floor_id": floor.id,
        "floor_name": floor.name,
    }


async def publish_projection_for_location(db: AsyncSession, location: Location) -> None:
    payload = await build_projection_from_location(db, location)
    if payload:
        await _publish_projection(payload)


async def publish_projection_for_floor_plan(db: AsyncSession, floor_plan: FloorPlan) -> None:
    payload = await build_projection_from_floor_plan(db, floor_plan)
    if payload:
        await _publish_projection(payload)


async def publish_projection_for_floor(db: AsyncSession, floor: Floor) -> None:
    stmt = (
        select(Floor)
        .options(
            selectinload(Floor.building),
            selectinload(Floor.locations),
            selectinload(Floor.floor_plans),
        )
        .where(Floor.id == floor.id)
    )
    result = await db.execute(stmt)
    db_floor = result.scalars().first()
    if not db_floor:
        return

    for location in db_floor.locations:
        payload = await build_projection_from_location(
            db,
            location,
            building_id=db_floor.building_id,
        )
        if payload:
            await _publish_projection(payload)

    for floor_plan in db_floor.floor_plans:
        payload = await build_projection_from_floor_plan(db, floor_plan)
        if payload:
            await _publish_projection(payload)


async def publish_projection_for_building(db: AsyncSession, building: Building) -> None:
    stmt = (
        select(Floor)
        .options(
            selectinload(Floor.building),
            selectinload(Floor.locations),
            selectinload(Floor.floor_plans),
        )
        .where(Floor.building_id == building.id)
    )
    result = await db.execute(stmt)
    floors = result.scalars().all()
    if not floors:
        return

    for floor in floors:
        for location in floor.locations:
            payload = await build_projection_from_location(
                db,
                location,
                building_id=building.id,
            )
            if payload:
                await _publish_projection(payload)
        for floor_plan in floor.floor_plans:
            payload = await build_projection_from_floor_plan(db, floor_plan)
            if payload:
                await _publish_projection(payload)
