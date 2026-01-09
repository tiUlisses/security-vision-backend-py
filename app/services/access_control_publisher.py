# app/services/access_control_publisher.py
from __future__ import annotations

import json
import logging
from datetime import datetime, time
from typing import Any

from asyncio_mqtt import Client as MQTTClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud.device_topic import device_topic as crud_device_topic
from app.models.device import Device
from app.models.location import Location, LocationRule
from app.models.user import User

logger = logging.getLogger(__name__)


def _slug(value: str, default: str) -> str:
    v = (value or "").strip()
    if not v:
        v = default
    v = v.lower()
    v = v.replace(" ", "_").replace("/", "-")
    return v


def _serialize_datetime(value: datetime | None) -> str | None:
    if not value:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.now().astimezone().tzinfo).isoformat()
    return value.isoformat()


def _serialize_time(value: time | None) -> str | None:
    if not value:
        return None
    return value.isoformat()


def _normalize_location_status(status: str | None) -> bool:
    return (status or "").upper() == "ACTIVE"


def _parse_avaliable_days(value: str | list[int] | None) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        parsed = []
        for item in value:
            try:
                parsed.append(int(item))
            except (TypeError, ValueError):
                continue
        return parsed
    if isinstance(value, str):
        parsed = []
        for part in value.split(","):
            trimmed = part.strip()
            if not trimmed:
                continue
            try:
                parsed.append(int(trimmed))
            except ValueError:
                continue
        return parsed
    return []


def _resolve_cpf(user: User) -> str | None:
    person = getattr(user, "person", None)
    if person and getattr(person, "document_id", None):
        return person.document_id
    document_id = getattr(user, "document_id", None)
    if document_id:
        return document_id
    cpf = getattr(user, "cpf", None)
    if cpf:
        return cpf
    return None


def _resolve_phone(user: User) -> str | None:
    for attr in ("phone", "phone_number", "mobile", "mobile_phone"):
        value = getattr(user, attr, None)
        if value:
            return value
    return None


def _resolve_user_type(user: User) -> str:
    role = getattr(user, "role", None)
    if role:
        return role
    return "UNKNOWN"


def _access_control_topic(*segments: str) -> str:
    base = settings.ACCESS_CONTROL_MQTT_BASE_TOPIC.rstrip("/")
    tenant = _slug(settings.ACCESS_CONTROL_TENANT, "default")
    cleaned = [segment.strip("/") for segment in segments if segment]
    return "/".join([base, tenant, *cleaned])


async def _mqtt_publish_json(topic: str, payload: dict[str, Any], *, retain: bool = True, qos: int = 1) -> None:
    if not settings.RTLS_MQTT_ENABLED:
        logger.debug("[access-control] RTLS_MQTT_ENABLED=false, não publicando em %s", topic)
        return

    host = settings.RTLS_MQTT_HOST
    port = settings.RTLS_MQTT_PORT
    username = settings.RTLS_MQTT_USERNAME or None
    password = settings.RTLS_MQTT_PASSWORD or None

    payload_str = json.dumps(payload, ensure_ascii=False)
    logger.info("[access-control] MQTT publish topic=%s retain=%s payload=%s", topic, retain, payload_str)

    async with MQTTClient(hostname=host, port=port, username=username, password=password) as client:
        await client.publish(topic, payload_str, qos=qos, retain=retain)


def _location_payload(location: Location) -> dict[str, Any]:
    return {
        "id": location.id,
        "name": location.name,
        "description": location.description,
        "status": _normalize_location_status(location.status),
        "floor_ids": [floor.id for floor in getattr(location, "floors", [])],
        "created_at": _serialize_datetime(location.created_at),
        "updated_at": _serialize_datetime(location.updated_at),
    }


def _location_rule_payload(rule: LocationRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "location_id": rule.location_id,
        "capacity": rule.capacity,
        "avaliable_days": _parse_avaliable_days(rule.avaliable_days),
        "start_time": _serialize_time(rule.start_time),
        "end_time": _serialize_time(rule.end_time),
        "status": rule.status,
        "validate": rule.validate,
        "created_at": _serialize_datetime(rule.created_at),
        "updated_at": _serialize_datetime(rule.updated_at),
    }


def _user_payload(user: User) -> dict[str, Any]:
    cpf = _resolve_cpf(user)
    phone = _resolve_phone(user)
    user_type = _resolve_user_type(user)
    if cpf is None:
        logger.warning("[access-control] user %s sem cpf definido; usando vazio no payload", user.id)
    if phone is None:
        logger.warning("[access-control] user %s sem phone definido; usando vazio no payload", user.id)
    if user_type == "UNKNOWN":
        logger.warning("[access-control] user %s sem role definido; user_type=UNKNOWN", user.id)

    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "user_type": user_type,
        "cpf": cpf or "",
        "phone": phone or "",
        "is_active": user.is_active,
        "created_at": _serialize_datetime(user.created_at),
        "updated_at": _serialize_datetime(user.updated_at),
    }


def _device_payload(device: Device) -> dict[str, Any]:
    return {
        "id": device.id,
        "name": device.name,
        "type": device.type,
        "description": device.description,
        "code": device.code,
        "mac_address": device.mac_address,
        "ip_address": device.ip_address,
        "port": device.port,
        "username": device.username,
        "building_id": device.building_id,
        "floor_id": device.floor_id,
        "created_at": _serialize_datetime(device.created_at),
        "updated_at": _serialize_datetime(device.updated_at),
    }


async def publish_access_control_location_created(location: Location) -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("location", str(location.id), "created")
    payload = {
        "event": "created",
        "location": _location_payload(location),
    }
    await _mqtt_publish_json(topic, payload, retain=True, qos=1)
    return topic, payload


async def publish_access_control_user_created(user: User) -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("user", str(user.id), "created")
    payload = {
        "event": "created",
        "user": _user_payload(user),
    }
    await _mqtt_publish_json(topic, payload, retain=True, qos=1)
    return topic, payload


async def publish_access_control_location_rule_created(rule: LocationRule) -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("location_rule", str(rule.id), "created")
    payload = {
        "event": "created",
        "location_rule": _location_rule_payload(rule),
    }
    await _mqtt_publish_json(topic, payload, retain=True, qos=1)
    return topic, payload


async def publish_access_control_device_created(
    db: AsyncSession,
    device: Device,
) -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("device", str(device.id), "created")
    payload = {
        "event": "created",
        "device": _device_payload(device),
    }
    await _mqtt_publish_json(topic, payload, retain=True, qos=1)

    await crud_device_topic.upsert(
        db,
        device_id=device.id,
        kind="access_control_device_created",
        topic=topic,
        description="Access control device created event",
    )
    await db.commit()

    return topic, payload


async def publish_access_control_device_user_created(
    device_id: int,
    user_id: int,
) -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("device_user", f"{device_id}-{user_id}", "created")
    payload = {
        "event": "created",
        "device_user": {
            "device_id": device_id,
            "user_id": user_id,
        },
    }
    await _mqtt_publish_json(topic, payload, retain=True, qos=1)
    return topic, payload


async def disable_access_control_topics_for_device(
    db: AsyncSession,
    device_id: int,
) -> None:
    topics = await crud_device_topic.list_by_device(db, device_id=device_id, only_active=True)
    if not topics:
        return

    for t in topics:
        if t.kind == "access_control_device_created":
            await _mqtt_publish_json(t.topic, {"enabled": False}, retain=True, qos=1)

    await crud_device_topic.mark_all_inactive(db, device_id=device_id)
    await db.commit()
