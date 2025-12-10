# app/services/cambus_event_collector.py
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from importlib import import_module
from typing import Optional
from datetime import datetime, timezone
from asyncio_mqtt import Client, MqttError
from sqlalchemy import select

from app.core.config import settings
from app.models.device import Device
from app.models.device_topic import DeviceTopic
from app.models.device_event import DeviceEvent
from app.crud.device_topic import device_topic as crud_device_topic

logger = logging.getLogger("cambus_event_collector")

# ---------------------------------------------------------------------------
# Descoberta dinâmica de como abrir sessão async no seu projeto
# ---------------------------------------------------------------------------

_session_mod = import_module("app.db.session")

_SessionFactory = None

if hasattr(_session_mod, "async_session"):
    _SessionFactory = _session_mod.async_session
    logger.info("[cambus] usando app.db.session.async_session para abrir sessões")

elif hasattr(_session_mod, "AsyncSessionLocal"):
    _maker = getattr(_session_mod, "AsyncSessionLocal")

    @asynccontextmanager
    async def _SessionFactory():
        async with _maker() as session:
            yield session

    logger.info("[cambus] usando AsyncSessionLocal() de app.db.session")

elif hasattr(_session_mod, "SessionLocal"):
    _maker = getattr(_session_mod, "SessionLocal")

    @asynccontextmanager
    async def _SessionFactory():
        async with _maker() as session:
            yield session

    logger.info("[cambus] usando SessionLocal() de app.db.session")

else:
    logger.error(
        "[cambus] NÃO encontrei nenhuma factory async em app.db.session "
        "(async_session / AsyncSessionLocal / SessionLocal). "
        "Coletor de eventos ficará desabilitado."
    )

    @asynccontextmanager
    async def _SessionFactory():
        raise RuntimeError(
            "Nenhuma factory async de sessão encontrada em app.db.session"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _slug(value: str | None, default: str) -> str:
    """
    Mesmo comportamento do _slug do cambus_publisher:
    - lower
    - espaços -> "_"
    - "/" -> "-"
    """
    v = (value or "").strip()
    if not v:
        v = default
    v = v.lower()
    v = v.replace(" ", "_").replace("/", "-")
    return v

def _parse_timestamp(payload: dict) -> datetime:
    candidates = [
        payload.get("Timestamp"),
        payload.get("timestamp"),
        payload.get("dateTime"),
    ]
    for ts in candidates:
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc)
        except Exception:
            continue

    return datetime.now(timezone.utc)


def _extract_analytic_type(payload: dict, kind: str, analytic_segment: Optional[str]) -> str:
    if kind == "cambus_event" and analytic_segment:
        # Para eventos, preferimos o segmento do tópico (faceCapture, VMD, etc.)
        return analytic_segment

    return (
        payload.get("AnalyticType")
        or payload.get("analyticType")
        or payload.get("eventType")
        or kind  # "cambus_info", "cambus_status", etc.
    )


def _parse_cambus_topic(topic: str) -> Optional[dict]:
    """
    Entende padrões do cam-bus em GO.

    Exemplos:

    - rtls/cameras/howbe/predioa/andar1/camera/fixa02/info
    - rtls/cameras/howbe/predioa/andar1/camera/fixa02/status
    - rtls/cameras/howbe/predioa/andar1/camera/fixa02/faceCapture/events
    - rtls/cameras/howbe/predioa/collector/status

    Retorna dict com:
      {
        "kind": "cambus_info" | "cambus_status" | "cambus_event" | "collector_status",
        "tenant": str,
        "building": str,
        "floor": Optional[str],
        "device_type": Optional[str],
        "device_code": Optional[str],
        "analytic": Optional[str],
      }
    ou None se não reconhecer o padrão.
    """
    base = settings.CAMBUS_MQTT_BASE_TOPIC.rstrip("/")
    base_parts = base.split("/")
    parts = topic.split("/")

    if parts[: len(base_parts)] != base_parts:
        return None

    offset = len(base_parts)
    if len(parts) <= offset:
        return None

    # Depois do base: tenant, building, ...
    # Índices relativos: offset + 0 = tenant, offset + 1 = building, ...
    tenant = parts[offset] if len(parts) > offset else None
    building = parts[offset + 1] if len(parts) > offset + 1 else None

    # Padrão collector/status: base/tenant/building/collector/status
    if len(parts) == offset + 4 and parts[offset + 2] == "collector" and parts[-1] == "status":
        return {
            "kind": "collector_status",
            "tenant": tenant,
            "building": building,
            "floor": None,
            "device_type": "collector",
            "device_code": None,
            "analytic": None,
        }

    tail = parts[-1]

    # Padrão câmera info/status: base/tenant/building/floor/camera/code/(info|status)
    if tail in ("info", "status") and len(parts) >= offset + 6:
        floor = parts[offset + 2]
        device_type = parts[offset + 3]
        device_code = parts[offset + 4]

        kind = "cambus_info" if tail == "info" else "cambus_status"

        return {
            "kind": kind,
            "tenant": tenant,
            "building": building,
            "floor": floor,
            "device_type": device_type,
            "device_code": device_code,
            "analytic": None,
        }

    # Padrão câmera eventos: base/tenant/building/floor/camera/code/analytic/events
    if tail == "events" and len(parts) >= offset + 7:
        floor = parts[offset + 2]
        device_type = parts[offset + 3]
        device_code = parts[offset + 4]
        analytic = parts[offset + 5]

        return {
            "kind": "cambus_event",
            "tenant": tenant,
            "building": building,
            "floor": floor,
            "device_type": device_type,
            "device_code": device_code,
            "analytic": analytic,
        }

    return None


# ---------------------------------------------------------------------------
# Handler de mensagem
# ---------------------------------------------------------------------------

async def _handle_message(topic: str, payload: bytes) -> None:
    logger.info("[cambus] mensagem recebida em %s", topic)

    info = _parse_cambus_topic(topic)
    if not info:
        logger.debug("[cambus] tópico %s não reconhecido pelo parser, ignorando", topic)
        return

    kind = info["kind"]
    device_type = info["device_type"]
    device_code = info["device_code"]
    analytic_segment = info["analytic"]

    # Por enquanto, vamos focar em CÂMERAS; collector_status podemos ignorar
    if kind == "collector_status":
        logger.debug("[cambus] tópico de collector_status %s, ignorando por enquanto", topic)
        return

    if not device_code or device_type != "camera":
        logger.debug(
            "[cambus] tópico %s não parece de câmera válida (device_type=%s, device_code=%s); ignorando",
            topic,
            device_type,
            device_code,
        )
        return

    try:
        data = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        logger.warning("[cambus] payload inválido em %s: %s", topic, exc)
        return

    try:
        async with _SessionFactory() as db:
            # Descobre o Device pela code + type
            stmt_dev = select(Device).where(
                Device.code == device_code,
                Device.type == "CAMERA",
            )
            result_dev = await db.execute(stmt_dev)
            device = result_dev.scalars().first()

            # Fallback: tenta casar pelo "slug" do code (mesma lógica do publisher)
            if not device:
                stmt_all = select(Device).where(Device.type == "CAMERA")
                result_all = await db.execute(stmt_all)
                cams = result_all.scalars().all()

                for d in cams:
                    slug_code = _slug(d.code or f"device{d.id}", f"device{d.id}")
                    if slug_code == device_code:
                        device = d
                        break

            if not device:
                logger.info(
                    "[cambus] nenhum Device CAMERA com code=%s (nem slug) encontrado para tópico %s",
                    device_code,
                    topic,
                )
                return

            # 1) Atualiza/cadastra o tópico em device_topics
            desc_map = {
                "cambus_info": "Camera /info for cam-bus",
                "cambus_status": "Camera status for cam-bus",
                "cambus_event": f"Camera event topic ({analytic_segment})",
            }
            desc = desc_map.get(kind, f"Camera topic ({kind})")

            await crud_device_topic.upsert(
                db,
                device_id=device.id,
                kind=kind,
                topic=topic,
                description=desc,
            )

            analytic_type = _extract_analytic_type(data, kind, analytic_segment)
            occurred_at = _parse_timestamp(data)

            # Normaliza para UTC naive (sem tzinfo) para bater com TIMESTAMP WITHOUT TIME ZONE
            if occurred_at.tzinfo is not None:
                occurred_at_naive = occurred_at.astimezone(timezone.utc).replace(tzinfo=None)
            else:
                occurred_at_naive = occurred_at

            # 1) Atualiza/cadastra o tópico em device_topics
            desc_map = {
                "cambus_info": "Camera /info for cam-bus",
                "cambus_status": "Camera status for cam-bus",
                "cambus_event": f"Camera event topic ({analytic_segment})",
            }
            desc = desc_map.get(kind, f"Camera topic ({kind})")

            await crud_device_topic.upsert(
                db,
                device_id=device.id,
                kind=kind,
                topic=topic,
                description=desc,
            )

            # 2) Atualiza last_seen_at do device (em UTC naive)
            current_last_seen = getattr(device, "last_seen_at", None)
            if current_last_seen is None or occurred_at_naive > current_last_seen:
                device.last_seen_at = occurred_at_naive

            # 3) Grava evento em device_events usando o mesmo occurred_at_naive
            ev = DeviceEvent(
                device_id=device.id,
                topic=topic,
                analytic_type=analytic_type,
                payload=data,
                occurred_at=occurred_at_naive,
            )
            db.add(ev)

            await db.commit()

            logger.info(
                "[cambus] evento gravado: device_id=%s kind=%s analytic=%s topic=%s",
                device.id,
                kind,
                analytic_type,
                topic,
            )
    except RuntimeError as exc:
        logger.error("[cambus] não foi possível abrir sessão de banco: %s", exc)
    except Exception as exc:
        logger.exception("[cambus] erro ao salvar evento no banco: %s", exc)


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------

async def run_cambus_event_collector() -> None:
    """
    Loop principal: conecta no broker, assina CAMBUS_MQTT_BASE_TOPIC/#
    e processa todos os tópicos das câmeras (info/status/events).
    """
    if not settings.CAMBUS_MQTT_ENABLED:
        logger.info("[cambus] CAMBUS_MQTT_ENABLED=false, coletor desabilitado")
        return

    host = settings.MQTT_HOST
    port = settings.MQTT_PORT
    base_topic = settings.CAMBUS_MQTT_BASE_TOPIC.rstrip("/")
    topic_filter = f"{base_topic}/#"

    logger.info(
        "[cambus] iniciando coletor em %s:%s, filtro=%s",
        host,
        port,
        topic_filter,
    )

    reconnect_interval = 5

    while True:
        try:
            async with Client(hostname=host, port=port) as client:
                async with client.messages() as messages:
                    await client.subscribe(topic_filter)
                    logger.info(
                        "[cambus] conectado ao broker e inscrito em %s",
                        topic_filter,
                    )

                    async for msg in messages:
                        topic = str(msg.topic)
                        await _handle_message(topic, msg.payload)

        except asyncio.CancelledError:
            logger.info("[cambus] coletor cancelado, saindo...")
            raise

        except MqttError as exc:
            logger.error(
                "[cambus] erro no MQTT (%s), tentando reconectar em %ss",
                exc,
                reconnect_interval,
            )
            await asyncio.sleep(reconnect_interval)

        except Exception as exc:
            logger.exception("[cambus] erro inesperado no coletor: %s", exc)
            await asyncio.sleep(reconnect_interval)
