import asyncio
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple
from app.crud import device as crud_device
from asyncio_mqtt import Client, MqttError
from sqlalchemy import select
from app.crud.device import get_or_create_gateway_by_mac
from app.core.config import Settings, settings
from app.db.session import AsyncSessionLocal
from app.models import Building, Floor
from app.models.device import Device
from app.schemas import CollectionLogCreate
from app.services.alert_engine import (
    fire_gateway_offline_event,
    fire_gateway_online_event,
    process_detection,
    close_stale_rtls_sessions,
)
from app.utils.mac import normalize_mac

logger = logging.getLogger("rtls.mqtt_ingestor")


def _decode_payload(payload: bytes) -> Optional[Any]:
    """Decode MQTT payload into Python object.

    Supports:
    - dict (single record)
    - list (batch records)  ✅ (your gateway sends this)
    """
    try:
        text = payload.decode("utf-8")
    except Exception:
        logger.warning("Failed to decode MQTT payload as UTF-8")
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Received non-JSON MQTT payload: %s", text)
        return None


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


@dataclass(frozen=True)
class GatewayTopicInfo:
    """Parsed gateway topic."""

    tenant: Optional[str]
    building: Optional[str]
    floor: Optional[str]
    gateway_id: Optional[str]
    kind: Optional[str]
    is_new_format: bool


class MqttIngestor:
    """MQTT ingestor for RTLS gateways.

    Accepts both formats:

    New (camera-like):
        rtls/gateways/<tenant>/<building>/<floor>/gateway/<gateway_id>/<kind>

    Legacy:
        rtls/gateways/<gateway_id>/<kind>
    """

    # legacy dict keys (kept for compatibility)
    TAG_MAC_KEYS = ("tag_mac", "tag", "tagMac", "mac")
    GATEWAY_MAC_KEYS = ("gateway_mac", "gateway", "gw_mac", "device_mac", "mac")
    RSSI_KEYS = ("rssi", "RSSI")

    def __init__(
        self,
        settings: Settings = settings,
        session_factory=AsyncSessionLocal,
        offline_check_interval_seconds: Optional[int] = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self._stopped = False

        if offline_check_interval_seconds is not None:
            self.offline_check_interval_seconds = offline_check_interval_seconds
        else:
            threshold = getattr(self.settings, "DEVICE_OFFLINE_THRESHOLD_SECONDS", 60)
            base = threshold // 2 or 5
            self.offline_check_interval_seconds = max(5, min(60, base))

        # device_id -> is_online
        self._gateway_status_cache: Dict[int, bool] = {}

    # ------------------------------------------------------------------
    # Topic parsing
    # ------------------------------------------------------------------

    def _parse_gateway_topic(self, topic: str) -> Optional[GatewayTopicInfo]:
        """Parse gateway topic into tenant/building/floor/gateway_id/kind."""
        prefix = self.settings.MQTT_GATEWAY_TOPIC_PREFIX.rstrip("/")
        if not topic.startswith(prefix):
            return None

        rest = topic[len(prefix) :].lstrip("/")
        if not rest:
            return None

        parts = [p for p in rest.split("/") if p]

        # New format:
        # <tenant>/<building>/<floor>/gateway/<gateway_id>/<kind?>
        if len(parts) >= 5 and parts[3].lower() == "gateway":
            tenant = parts[0]
            building = parts[1]
            floor = parts[2]
            gateway_id = parts[4]
            kind = parts[5] if len(parts) >= 6 else None
            return GatewayTopicInfo(
                tenant=tenant,
                building=building,
                floor=floor,
                gateway_id=gateway_id,
                kind=kind,
                is_new_format=True,
            )

        # Legacy format:
        # <gateway_id>/<kind?>
        gateway_id = parts[0] if parts else None
        kind = parts[1] if len(parts) >= 2 else None
        return GatewayTopicInfo(
            tenant=None,
            building=None,
            floor=None,
            gateway_id=gateway_id,
            kind=kind,
            is_new_format=False,
        )

    # ------------------------------------------------------------------
    # Location resolution (building/floor)
    # ------------------------------------------------------------------

    async def _resolve_building_floor_ids(
        self,
        db,
        building_seg: Optional[str],
        floor_seg: Optional[str],
    ) -> Tuple[Optional[int], Optional[int]]:
        if not building_seg:
            return None, None

        building_seg = str(building_seg).strip()
        floor_seg = str(floor_seg).strip() if floor_seg else None

        # Prefer exact match on Building.code (case-insensitive), then fallback to slug(name)
        stmt = select(Building)
        res = await db.execute(stmt)
        buildings = list(res.scalars().all())

        b = None
        seg_slug = _slug(building_seg)
        for cand in buildings:
            if cand.code and cand.code.lower() == building_seg.lower():
                b = cand
                break
        if b is None:
            for cand in buildings:
                if _slug(cand.name) == seg_slug or (cand.code and _slug(cand.code) == seg_slug):
                    b = cand
                    break

        if b is None:
            logger.warning(
                "MQTT: building '%s' not found in DB. Gateway will be created unassigned.",
                building_seg,
            )
            return None, None

        building_id = b.id
        floor_id: Optional[int] = None

        if floor_seg:
            stmt_f = select(Floor).where(Floor.building_id == building_id)
            res_f = await db.execute(stmt_f)
            floors = list(res_f.scalars().all())

            # numeric -> match by level
            level: Optional[int] = None
            try:
                if re.fullmatch(r"-?\d+", floor_seg):
                    level = int(floor_seg)
            except Exception:
                level = None

            if level is not None:
                for fl in floors:
                    if fl.level == level:
                        floor_id = fl.id
                        break

            if floor_id is None:
                seg_slug = _slug(floor_seg)
                for fl in floors:
                    if _slug(fl.name) == seg_slug:
                        floor_id = fl.id
                        break

            if floor_id is None:
                logger.warning(
                    "MQTT: floor '%s' not found for building '%s'. Gateway will keep only building_id.",
                    floor_seg,
                    b.code,
                )

        return building_id, floor_id

    # ------------------------------------------------------------------
    # Payload parsing (detections)
    # ------------------------------------------------------------------

    def _extract_int(self, obj: dict, keys: Iterable[str]) -> Optional[int]:
        for k in keys:
            if k in obj and obj[k] is not None:
                try:
                    return int(obj[k])
                except Exception:
                    return None
        return None

    def _extract_str(self, obj: dict, keys: Iterable[str]) -> Optional[str]:
        for k in keys:
            v = obj.get(k)
            if v:
                return str(v).strip()
        return None

    def _iter_detections(
        self,
        data: Any,
        *,
        gateway_mac_fallback: Optional[str],
    ) -> Tuple[Optional[str], Iterable[Tuple[str, Optional[int], dict]]]:
        """Return (gateway_mac, detections).

        detections yields tuples: (tag_mac, rssi, raw_record)
        """

        gw = normalize_mac(gateway_mac_fallback)

        # ---------------- list (your gateway) ----------------
        if isinstance(data, list):
            # detect gateway mac from records if present
            for rec in data:
                if isinstance(rec, dict) and str(rec.get("type", "")).lower() == "gateway":
                    gw = normalize_mac(rec.get("mac")) or gw

            def gen() -> Iterable[Tuple[str, Optional[int], dict]]:
                for rec in data:
                    if not isinstance(rec, dict):
                        continue

                    rtype = str(rec.get("type", "")).lower()
                    if rtype == "gateway":
                        continue

                    # iBeacon / beacon / tag
                    if rtype in ("ibeacon", "beacon", "tag"):
                        tag_mac = normalize_mac(rec.get("mac") or rec.get("tag_mac"))
                        if not tag_mac:
                            continue
                        rssi = self._extract_int(rec, self.RSSI_KEYS)
                        yield tag_mac, rssi, rec
                        continue

                    # fallback: if a record has 'rssi' and 'mac', treat as detection
                    if "rssi" in rec and (rec.get("mac") or rec.get("tag_mac")):
                        tag_mac = normalize_mac(rec.get("mac") or rec.get("tag_mac"))
                        if not tag_mac:
                            continue
                        rssi = self._extract_int(rec, self.RSSI_KEYS)
                        yield tag_mac, rssi, rec

            return gw, gen()

        # ---------------- dict (legacy) ----------------
        if isinstance(data, dict):
            tag_mac = normalize_mac(self._extract_str(data, self.TAG_MAC_KEYS))
            if not tag_mac:
                return gw, []

            gw = normalize_mac(self._extract_str(data, self.GATEWAY_MAC_KEYS)) or gw
            rssi = self._extract_int(data, self.RSSI_KEYS)
            return gw, [(tag_mac, rssi, data)]

        return gw, []

    # ------------------------------------------------------------------
    # Main message handler
    # ------------------------------------------------------------------

    async def handle_message(self, topic: str, payload: bytes) -> None:
        # asyncio-mqtt may provide a Topic object; normalize to str
        topic = str(topic)
        logger.info("MQTT message received: topic=%s", topic)

        ctx = self._parse_gateway_topic(topic)
        if not ctx:
            return

        now = datetime.utcnow()
        data = _decode_payload(payload)

        # Gateway MAC comes primarily from the topic, then from payload.
        topic_gw = normalize_mac(ctx.gateway_id)

        async with self.session_factory() as db:
            # Resolve location if new topic format provides building/floor
            building_id, floor_id = await self._resolve_building_floor_ids(
                db,
                ctx.building,
                ctx.floor,
            )

            # Ensure gateway exists (even if payload isn't JSON)
            from app.crud import device as crud_device

            gw_mac = topic_gw
            if not gw_mac and isinstance(data, dict):
                gw_mac = normalize_mac(self._extract_str(data, self.GATEWAY_MAC_KEYS))

            if not gw_mac:
                # Can't do anything without identifying gateway
                logger.warning("MQTT: could not determine gateway MAC for topic=%s", topic)
                return

            db_device = await get_or_create_gateway_by_mac(
                db,
                gw_mac,
                building_id=building_id,
                floor_id=floor_id,
            )

            # update usando a instância CRUD (não existe crud_device.device aqui)
            await crud_device.update(db, db_device, {"last_seen_at": now})

            # If we got no payload, stop here.
            if data is None:
                return

            # Extract detections and create logs for known tags
            gw_mac2, detections = self._iter_detections(data, gateway_mac_fallback=gw_mac)

            if gw_mac2 and gw_mac2 != gw_mac:
                # Update gateway mac if payload had a better one
                # (rare, but harmless).
                gw_mac = gw_mac2

            if not detections:
                return

            from app.crud import collection_log as crud_collection_log
            from app.crud import tag as crud_tag

            for tag_mac, rssi, rec in detections:
                db_tag = await crud_tag.get_by_mac(db, mac_address=tag_mac)
                if not db_tag:
                    logger.debug("Ignoring detection for unknown tag MAC: %s", tag_mac)
                    continue

                raw_payload = json.dumps(
                    {
                        "topic": topic,
                        "tenant": ctx.tenant,
                        "building": ctx.building,
                        "floor": ctx.floor,
                        "gateway_mac": gw_mac,
                        "record": rec,
                    },
                    ensure_ascii=False,
                )

                log_in = CollectionLogCreate(
                    device_id=db_device.id,
                    tag_id=db_tag.id,
                    rssi=rssi,
                    raw_payload=raw_payload,
                )
                created_log = await crud_collection_log.create(db, log_in)

                # Alert engine (não pode quebrar a coleta)
                try:
                    await process_detection(
                        db,
                        db_device,
                        db_tag,
                        collection_log_id=getattr(created_log, "id", None),
                    )
                except Exception:
                    logger.exception(
                        "AlertEngine failed for device_id=%s tag_id=%s",
                        db_device.id,
                        db_tag.id,
                    )

    # ------------------------------------------------------------------
    # Offline / online monitor
    # ------------------------------------------------------------------

    async def _handle_gateway_offline(
        self,
        db,
        device: Device,
        now: datetime,
        offline_seconds: int,
    ) -> None:
        logger.warning(
            "Gateway OFFLINE detected: id=%s name=%s mac=%s last_seen_at=%s offline_for=%ss",
            device.id,
            device.name,
            device.mac_address,
            device.last_seen_at,
            offline_seconds,
        )
        await fire_gateway_offline_event(
            db=db,
            device=device,
            now=now,
            offline_seconds=offline_seconds,
        )

    async def _handle_gateway_online(
        self,
        db,
        device: Device,
        now: datetime,
    ) -> None:
        logger.info(
            "Gateway ONLINE detected: id=%s name=%s mac=%s last_seen_at=%s",
            device.id,
            device.name,
            device.mac_address,
            device.last_seen_at,
        )
        await fire_gateway_online_event(
            db=db,
            device=device,
            now=now,
        )

    async def _offline_monitor_loop(self) -> None:
        interval = self.offline_check_interval_seconds
        threshold = getattr(self.settings, "DEVICE_OFFLINE_THRESHOLD_SECONDS", 30)

        logger.info(
            "Starting gateway offline monitor: interval=%ss threshold=%ss",
            interval,
            threshold,
        )

        while not self._stopped:
            await asyncio.sleep(interval)
            now = datetime.utcnow()

            try:
                async with self.session_factory() as db:
                    stmt = select(Device).where(Device.type == "BLE_GATEWAY")
                    result = await db.execute(stmt)
                    devices = result.scalars().all()

                    for dev in devices:
                        if dev.last_seen_at is None:
                            is_online = False
                            offline_seconds = None
                        else:
                            delta = (now - dev.last_seen_at).total_seconds()
                            is_online = delta <= threshold
                            offline_seconds = int(delta)

                        prev_status = self._gateway_status_cache.get(dev.id)

                        if prev_status is None:
                            self._gateway_status_cache[dev.id] = is_online
                            continue

                        if prev_status and not is_online:
                            if offline_seconds is not None:
                                await self._handle_gateway_offline(
                                    db,
                                    dev,
                                    now,
                                    offline_seconds,
                                )

                        if (not prev_status) and is_online:
                            await self._handle_gateway_online(db, dev, now)

                        self._gateway_status_cache[dev.id] = is_online
                    # ✅ ETAPA 2 aqui
                    try:
                        await close_stale_rtls_sessions(db, now=now)
                    except Exception:
                        logger.exception("Error closing stale RTLS sessions")
            except Exception as e:
                logger.exception("Error while running gateway offline monitor: %s", e)

    # ------------------------------------------------------------------
    # MQTT loop
    # ------------------------------------------------------------------

    async def _mqtt_loop(self) -> None:
        host = self.settings.MQTT_HOST
        port = self.settings.MQTT_PORT
        username = self.settings.MQTT_USERNAME
        password = self.settings.MQTT_PASSWORD
        topic = self.settings.MQTT_TOPIC

        backoff = 5

        logger.info(
            "Starting MQTT loop: host=%s port=%s topic=%s",
            host,
            port,
            topic,
        )

        while not self._stopped:
            try:
                async with Client(
                    hostname=host,
                    port=port,
                    username=username or None,
                    password=password or None,
                ) as client:
                    logger.info("Connected to MQTT broker %s:%s", host, port)

                    await client.subscribe(topic)
                    logger.info("Subscribed to topic: %s", topic)

                    backoff = 5

                    async with client.unfiltered_messages() as messages:
                        async for message in messages:
                            try:
                                await self.handle_message(
                                    message.topic,
                                    message.payload,
                                )
                            except Exception as e:
                                logger.exception("Error processing MQTT message: %s", e)

            except MqttError as e:
                logger.warning(
                    "MQTT connection error: %s. Reconnecting in %s seconds...",
                    e,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            except Exception as e:
                logger.exception("Unexpected error in MQTT ingestor: %s", e)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def run(self) -> None:
        tasks = []
        try:
            tasks.append(asyncio.create_task(self._mqtt_loop(), name="mqtt_loop"))

            threshold = getattr(self.settings, "DEVICE_OFFLINE_THRESHOLD_SECONDS", 0)
            if threshold > 0:
                tasks.append(
                    asyncio.create_task(
                        self._offline_monitor_loop(),
                        name="offline_monitor",
                    )
                )

            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            self._stopped = True
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            self._stopped = True

    def stop(self) -> None:
        self._stopped = True
