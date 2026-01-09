# app/services/access_control_publisher.py
from __future__ import annotations

import json
import logging
from datetime import datetime, time
from typing import Any

from asyncio_mqtt import Client as MQTTClient

from app.core.config import settings
from app.models.device import Device
from app.models.device_user import DeviceUser
from app.models.location import Location, LocationRule
from app.models.person import Person

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


def _resolve_device_location_id(device: Device) -> int | None:
    if device.location_id is not None:
        return device.location_id
    floor = getattr(device, "floor", None)
    if floor and getattr(floor, "locations", None):
        for location in floor.locations:
            if location and getattr(location, "id", None) is not None:
                return location.id
    return None


def _access_control_topic(*segments: str) -> str:
    base = settings.ACCESS_CONTROL_MQTT_BASE_TOPIC.rstrip("/")
    tenant = _slug(settings.ACCESS_CONTROL_TENANT, "default")
    cleaned = [segment.strip("/") for segment in segments if segment]
    return "/".join([base, tenant, *cleaned])


def _build_access_control_envelope(event: str, entity: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": event,
        "entity": entity,
        "source": "central-backend",
        "payload": payload,
    }


async def _mqtt_publish_raw(topic: str, payload: str, *, retain: bool = True, qos: int = 1) -> None:
    if not settings.ACCESS_CONTROL_MQTT_ENABLED:
        logger.debug("[access-control] ACCESS_CONTROL_MQTT_ENABLED=false, não publicando em %s", topic)
        return
    if not settings.RTLS_MQTT_ENABLED:
        logger.debug("[access-control] RTLS_MQTT_ENABLED=false, não publicando em %s", topic)
        return

    host = settings.RTLS_MQTT_HOST
    port = settings.RTLS_MQTT_PORT
    username = settings.RTLS_MQTT_USERNAME or None
    password = settings.RTLS_MQTT_PASSWORD or None

    logger.info("[access-control] MQTT publish topic=%s retain=%s payload=%s", topic, retain, payload)

    async with MQTTClient(hostname=host, port=port, username=username, password=password) as client:
        await client.publish(topic, payload, qos=qos, retain=retain)


async def _mqtt_publish_json(topic: str, payload: dict[str, Any], *, retain: bool = True, qos: int = 1) -> None:
    payload_str = json.dumps(payload, ensure_ascii=False)
    await _mqtt_publish_raw(topic, payload_str, retain=retain, qos=qos)


async def _mqtt_publish_empty(topic: str, *, retain: bool = True, qos: int = 1) -> None:
    await _mqtt_publish_raw(topic, "", retain=retain, qos=qos)


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


def _user_payload(person: Person) -> dict[str, Any]:
    document_id = person.document_id
    phone = person.phone
    user_type = person.user_type
    if document_id is None:
        logger.warning("[access-control] person %s sem document_id definido; usando vazio no payload", person.id)
    if phone is None:
        logger.warning("[access-control] person %s sem phone definido; usando vazio no payload", person.id)
    if user_type is None:
        logger.warning("[access-control] person %s sem user_type definido", person.id)

    return {
        "id": person.id,
        "email": person.email,
        "full_name": person.full_name,
        "document_id": document_id or "",
        "cpf": document_id or "",
        "phone": phone or "",
        "user_type": user_type if user_type is not None else "UNKNOWN",
        "is_active": person.active,
        "created_at": _serialize_datetime(person.created_at),
        "updated_at": _serialize_datetime(person.updated_at),
    }


def _device_payload(device: Device) -> dict[str, Any]:
    serial_number = device.code or device.mac_address
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
        "brand": device.manufacturer,
        "category": device.type,
        "serialNumber": serial_number,
        "config": device.analytics or {},
        "locationId": _resolve_device_location_id(device),
        "created_at": _serialize_datetime(device.created_at),
        "updated_at": _serialize_datetime(device.updated_at),
    }


async def publish_access_control_location_created(location: Location) -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("locations", "created")
    payload = _build_access_control_envelope("created", "location", _location_payload(location))
    await _mqtt_publish_json(topic, payload, retain=True, qos=1)
    return topic, payload


async def publish_access_control_location_updated(location: Location) -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("locations", "updated")
    payload = _build_access_control_envelope("updated", "location", _location_payload(location))
    await _mqtt_publish_json(topic, payload, retain=True, qos=1)
    return topic, payload


async def publish_access_control_location_deleted() -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("locations", "deleted")
    await _mqtt_publish_empty(topic, retain=True, qos=1)
    return topic, {}


async def publish_access_control_user_created(person: Person) -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("users", "created")
    payload = _build_access_control_envelope("created", "user", _user_payload(person))
    await _mqtt_publish_json(topic, payload, retain=True, qos=1)
    return topic, payload


async def publish_access_control_user_updated(person: Person) -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("users", "updated")
    payload = _build_access_control_envelope("updated", "user", _user_payload(person))
    await _mqtt_publish_json(topic, payload, retain=True, qos=1)
    return topic, payload


async def publish_access_control_user_deleted() -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("users", "deleted")
    await _mqtt_publish_empty(topic, retain=True, qos=1)
    return topic, {}


async def publish_access_control_location_rule_created(rule: LocationRule) -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("locations-rules", "created")
    payload = _build_access_control_envelope("created", "location_rule", _location_rule_payload(rule))
    await _mqtt_publish_json(topic, payload, retain=True, qos=1)
    return topic, payload


async def publish_access_control_location_rule_updated(rule: LocationRule) -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("locations-rules", "updated")
    payload = _build_access_control_envelope("updated", "location_rule", _location_rule_payload(rule))
    await _mqtt_publish_json(topic, payload, retain=True, qos=1)
    return topic, payload


async def publish_access_control_location_rule_deleted() -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("locations-rules", "deleted")
    await _mqtt_publish_empty(topic, retain=True, qos=1)
    return topic, {}


async def publish_access_control_device_created(
    device: Device,
) -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("devices", "created")
    payload = _build_access_control_envelope("created", "device", _device_payload(device))
    await _mqtt_publish_json(topic, payload, retain=True, qos=1)
    return topic, payload


async def publish_access_control_device_updated(
    device: Device,
) -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("devices", "updated")
    payload = _build_access_control_envelope("updated", "device", _device_payload(device))
    await _mqtt_publish_json(topic, payload, retain=True, qos=1)
    return topic, payload


async def publish_access_control_device_deleted() -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("devices", "deleted")
    await _mqtt_publish_empty(topic, retain=True, qos=1)
    return topic, {}


async def publish_access_control_device_user_created(
    device_user: DeviceUser,
) -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("device-users", "created")
    payload = _build_access_control_envelope(
        "created",
        "device_user",
        {
            "device_id": device_user.device_id,
            "person_id": device_user.person_id,
            "deviceUserId": device_user.device_user_id,
            "status": device_user.status,
        },
    )
    await _mqtt_publish_json(topic, payload, retain=True, qos=1)
    return topic, payload


async def publish_access_control_device_user_updated(
    device_user: DeviceUser,
) -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("device-users", "updated")
    payload = _build_access_control_envelope(
        "updated",
        "device_user",
        {
            "device_id": device_user.device_id,
            "person_id": device_user.person_id,
            "deviceUserId": device_user.device_user_id,
            "status": device_user.status,
        },
    )
    await _mqtt_publish_json(topic, payload, retain=True, qos=1)
    return topic, payload


async def publish_access_control_device_user_deleted() -> tuple[str, dict[str, Any]]:
    topic = _access_control_topic("device-users", "deleted")
    await _mqtt_publish_empty(topic, retain=True, qos=1)
    return topic, {}
