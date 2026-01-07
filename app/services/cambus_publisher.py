# app/services/cambus_publisher.py
from __future__ import annotations

import json
import logging
from typing import List

from asyncio_mqtt import Client as MQTTClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.building import Building
from app.models.floor import Floor
from app.models.device import Device
from app.crud.device_topic import device_topic as crud_device_topic

logger = logging.getLogger(__name__)


def _slug(value: str, default: str) -> str:
    v = (value or "").strip()
    if not v:
        v = default
    v = v.lower()
    v = v.replace(" ", "_").replace("/", "-")
    return v


async def _mqtt_publish_json(topic: str, payload: dict, *, retain: bool = True, qos: int = 1) -> None:
    if not settings.CAMBUS_MQTT_ENABLED:
        logger.debug("[cam-bus] CAMBUS_MQTT_ENABLED=false, não publicando em %s", topic)
        return
    if not settings.RTLS_MQTT_ENABLED:
        logger.debug("[cam-bus] RTLS_MQTT_ENABLED=false, não publicando em %s", topic)
        return

    host = settings.RTLS_MQTT_HOST
    port = settings.RTLS_MQTT_PORT
    username = settings.RTLS_MQTT_USERNAME or None
    password = settings.RTLS_MQTT_PASSWORD or None

    payload_str = json.dumps(payload, ensure_ascii=False)
    logger.info("[cam-bus] MQTT publish topic=%s retain=%s payload=%s", topic, retain, payload_str)

    async with MQTTClient(hostname=host, port=port, username=username, password=password) as client:
        await client.publish(topic, payload_str, qos=qos, retain=retain)


async def _resolve_building_floor(
    db: AsyncSession,
    device: Device,
) -> tuple[str, str]:
    # ✅ NOVO: se não tiver prédio/andar, mandamos pra "externo/externo"
    # (principalmente para câmeras que foram desassociadas)
    if getattr(device, "type", None) == "CAMERA" and not device.building_id and not device.floor_id:
        return _slug("externo", "externo"), _slug("externo", "externo")

    b_name = "building"
    f_name = "floor"

    if device.building_id:
        stmt = select(Building).where(Building.id == device.building_id)
        result = await db.execute(stmt)
        b = result.scalars().first()
        if b and getattr(b, "name", None):
            b_name = b.name

    if device.floor_id:
        stmt = select(Floor).where(Floor.id == device.floor_id)
        result = await db.execute(stmt)
        f = result.scalars().first()
        if f and getattr(f, "name", None):
            f_name = f.name

    return _slug(b_name, "building"), _slug(f_name, "floor")


def _analytics_for_device(device: Device) -> List[str]:
    """
    Define quais analytics o cam-bus deve assinar para esta câmera.

    1) Se device.analytics estiver preenchido (lista de strings), usamos ESSA lista.
    2) Senão, caímos nos defaults por fabricante (Dahua/Hikvision).
    """
    # 1) Se usuário configurou na UI → usa isso
    if getattr(device, "analytics", None):
        # garante que é lista de string
        return [str(a) for a in device.analytics if a]

    # 2) Fallback por fabricante (comportamento antigo)
    manuf = (device.manufacturer or "").lower()

    if "hikvision" in manuf:
        # exemplo: defaults
        return ["faceCapture", "VMD"]

    if "dahua" in manuf:
        return ["FaceDetection", "CrossLineDetection", "CrossRegionDetection"]

    # fallback genérico
    return ["faceCapture"]


async def publish_camera_info_from_device(
    db: AsyncSession,
    device: Device,
) -> None:
    """
    Publica o /info da câmera no MQTT no formato esperado pelo cam-bus em GO
    e registra os tópicos correspondentes em device_topics.

    Tópico:
      <CAMBUS_MQTT_BASE_TOPIC>/<tenant>/<building>/<floor>/camera/<code>/info
    """
    if getattr(device, "type", None) != "CAMERA":
        logger.debug("[cam-bus] device %s (%s) não é CAMERA, ignorando publish /info", device.id, device.name)
        return

    base = settings.CAMBUS_MQTT_BASE_TOPIC.rstrip("/")
    tenant = _slug(settings.CAMBUS_TENANT, "default")

    building_slug, floor_slug = await _resolve_building_floor(db, device)

    cam_id = (device.code or f"device{device.id}").strip()
    cam_id = _slug(cam_id, f"device{device.id}")

    info_topic = f"{base}/{tenant}/{building_slug}/{floor_slug}/camera/{cam_id}/info"

    analytics = _analytics_for_device(device)

    payload = {
        "manufacturer": device.manufacturer or "",
        "model": device.model or "",
        "name": device.name,
        "ip": device.ip_address,
        "username": device.username or "",
        "password": device.password or "",
        "port": device.port or 80,
        "use_tls": False,  # se precisar, podemos mapear de um campo depois
        "enabled": True,
        "shard": device.shard or settings.CAMBUS_DEFAULT_SHARD,
        "analytics": analytics,
        "rtsp_url": device.rtsp_url or "",
        "proxy_path": device.proxy_path or "",
        "central_path": device.central_path or "",
        "record_retention_minutes": device.record_retention_minutes,
        "central_media_mtx_ip": device.central_media_mtx_ip or "",
    }

    # 1) Publica /info no MQTT
    await _mqtt_publish_json(info_topic, payload, retain=True, qos=1)

# 2) Registra tópicos em device_topics
    #    - /info (kind=cambus_info)
    #    - /events por analytic (kind=cambus_event)
    await crud_device_topic.upsert(
        db,
        device_id=device.id,
        kind="cambus_info",
        topic=info_topic,
        description="Camera /info for cam-bus",
    )

    for analytic in analytics:
        # ⚠️ Aqui usamos o analytic EXACTAMENTE como o GO vai usar no AnalyticType
        # Nada de slug/lowercase, para o tópico bater 100%.
        analytic_segment = analytic

        event_topic = (
            f"{base}/{tenant}/{building_slug}/{floor_slug}/camera/{cam_id}/{analytic_segment}/events"
        )

        await crud_device_topic.upsert(
            db,
            device_id=device.id,
            kind="cambus_event",
            topic=event_topic,
            description=f"Camera event topic ({analytic})",
        )

    await db.commit()


async def publish_camera_uplink_action_from_device(
    db: AsyncSession,
    device: Device,
    action: str,
) -> str:
    return await publish_camera_uplink_command(db, device, action)


async def publish_camera_uplink_command(
    db: AsyncSession,
    device: Device,
    action: str,
) -> str:
    """
    Publica comando uplink start/stop da câmera no MQTT.

    Tópico:
      <CAMBUS_UPLINK_BASE_TOPIC>/<tenant>/<building>/<floor>/camera/<code>/uplink/<action>
    """
    if getattr(device, "type", None) != "CAMERA":
        raise ValueError("Device não é do tipo CAMERA.")

    if action not in {"start", "stop"}:
        raise ValueError(f"Ação inválida para uplink: {action}")

    base = settings.CAMBUS_UPLINK_BASE_TOPIC.rstrip("/")
    tenant = _slug(settings.CAMBUS_TENANT, "default")

    building_slug, floor_slug = await _resolve_building_floor(db, device)

    cam_id = (device.code or f"device{device.id}").strip()
    cam_id = _slug(cam_id, f"device{device.id}")

    topic = f"{base}/{tenant}/{building_slug}/{floor_slug}/camera/{cam_id}/uplink/{action}"

    payload = {
        "cameraId": cam_id,
        "proxyPath": device.proxy_path,
        "centralPath": device.central_path,
        "centralHost": device.central_media_mtx_ip,
        "centralSrtPort": settings.CAMBUS_UPLINK_SRT_PORT,
        "ttlSeconds": settings.CAMBUS_UPLINK_TTL_SECONDS,
    }

    # retain=False por padrão, já que o proxy não espera comandos retidos.
    await _mqtt_publish_json(topic, payload, retain=False, qos=1)

    return topic

async def disable_cambus_topics_for_device(
    db: AsyncSession,
    device_id: int,
) -> None:
    """
    Marca todos os tópicos de um device como inativos e,
    para os tópicos de /info, publica enabled=false (retain)
    para o cam-bus desativar o worker antigo.
    """
    topics = await crud_device_topic.list_by_device(db, device_id=device_id, only_active=True)
    if not topics:
        return

    # Publica "enabled=false" apenas nos tópicos de /info (cambus_info)
    for t in topics:
        if t.kind == "cambus_info":
            await _mqtt_publish_json(t.topic, {"enabled": False}, retain=True, qos=1)

    # Marca todos como inativos (mantém histórico)
    await crud_device_topic.mark_all_inactive(db, device_id=device_id)
    await db.commit()
