import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from asyncio_mqtt import Client, MqttError
from sqlalchemy import select

from app.core.config import Settings, settings
from app.db.session import AsyncSessionLocal
from app.schemas import CollectionLogCreate, DeviceCreate
from app.services.alert_engine import (
    process_detection,
    fire_gateway_offline_event,
    fire_gateway_online_event,
)
from app.models.device import Device

logger = logging.getLogger("rtls.mqtt_ingestor")


def _decode_payload(payload: bytes) -> Optional[dict]:
    """
    Decodifica payload MQTT para dict JSON.
    Retorna None se não conseguir decodificar.
    """
    try:
        text = payload.decode("utf-8")
    except Exception:
        logger.warning("Failed to decode MQTT payload as UTF-8")
        return None

    try:
        data = json.loads(text)
        return data
    except json.JSONDecodeError:
        logger.warning("Received non-JSON MQTT payload: %s", text)
        return None


class MqttIngestor:
    """
    Ingestor MQTT:

    - Tudo que chegar em tópicos com prefixo MQTT_GATEWAY_TOPIC_PREFIX:
        * é considerado tráfego de GATEWAY
        * auto-cadastra Device (se não existir)
        * atualiza last_seen_at (para online/offline)

    - Mensagens de detecção (TAG vista por GATEWAY), normalmente em tópico MQTT_TOPIC
      (ex: "rtls/detections" ou algo sob o prefixo do gateway):
        * se Tag conhecida -> grava CollectionLog
        * se Tag desconhecida -> IGNORA (cadastro manual de tags)
        * garante que o gateway exista (auto-cadastro se necessário)
        * atualiza last_seen_at do gateway
        * dispara process_detection() para regras/alertas

    - Monitor interno de OFFLINE:
        * periodicamente lê devices BLE_GATEWAY
        * calcula se passaram mais que DEVICE_OFFLINE_THRESHOLD_SECONDS sem publicar
        * detecta transições ONLINE -> OFFLINE e OFFLINE -> ONLINE
        * chama handlers (_handle_gateway_offline / _handle_gateway_online) para você plugar
          em AlertEvent / Webhook no futuro.
    """

    # chaves do payload para facilitar adaptação ao gateway real
    TAG_MAC_KEYS = ("tag_mac", "tag", "tagMac")
    GATEWAY_MAC_KEYS = ("gateway_mac", "gateway", "gw_mac", "device_mac")
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

        # Intervalo do monitor de offline (segundos)
        if offline_check_interval_seconds is not None:
            self.offline_check_interval_seconds = offline_check_interval_seconds
        else:
            threshold = getattr(self.settings, "DEVICE_OFFLINE_THRESHOLD_SECONDS", 60)
            base = threshold // 2 or 5
            self.offline_check_interval_seconds = max(5, min(60, base))

        # Estado em memória para detectar transições online/offline
        # device_id -> is_online (bool)
        self._gateway_status_cache: Dict[int, bool] = {}

    # ------------------------------------------------------------------
    # Helpers internos de tópico e payload
    # ------------------------------------------------------------------

    def _extract_gateway_id_from_topic(self, topic: str) -> Optional[str]:
        """
        Extrai o identificador (geralmente MAC ou código) do gateway
        a partir do tópico, usando o prefixo configurado.

        Exemplo:
            prefixo = "rtls/gw"
            topic   = "rtls/gw/AA:BB:CC:DD:EE:FF/heartbeat"
            -> retorna "AA:BB:CC:DD:EE:FF"

        Se, no futuro, o seu gateway real usar outra estrutura de tópico,
        é só ajustar este método.
        """
        prefix = self.settings.MQTT_GATEWAY_TOPIC_PREFIX.rstrip("/")
        if not topic.startswith(prefix):
            return None

        rest = topic[len(prefix) :].lstrip("/")
        if not rest:
            return None

        parts = rest.split("/")
        return parts[0] if parts else None

    def _extract_tag_mac_from_data(self, data: dict) -> Optional[str]:
        """
        Tenta obter o MAC da TAG a partir do payload JSON, usando
        as chaves definidas em TAG_MAC_KEYS.
        """
        for key in self.TAG_MAC_KEYS:
            value = data.get(key)
            if value:
                return str(value).strip()
        return None

    def _extract_gateway_mac_from_data(self, data: dict, topic: str) -> Optional[str]:
        """
        Tenta obter o MAC do gateway a partir do payload JSON e,
        se não encontrar, tenta extrair do tópico MQTT.
        """
        for key in self.GATEWAY_MAC_KEYS:
            value = data.get(key)
            if value:
                return str(value).strip()

        return self._extract_gateway_id_from_topic(topic)

    def _extract_rssi_from_data(self, data: dict) -> Optional[int]:
        """
        Tenta obter RSSI como int a partir do payload JSON.
        """
        for key in self.RSSI_KEYS:
            value = data.get(key)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
        return None

    async def _get_or_create_gateway(self, db, gateway_mac: str) -> Device:
        """
        Garante que o gateway exista como Device BLE_GATEWAY
        e atualiza last_seen_at.
        """
        from app.crud import device as crud_device

        mac = str(gateway_mac).strip()
        now = datetime.utcnow()

        db_device = await crud_device.get_by_mac(db, mac_address=mac)
        if not db_device:
            # auto-cadastro do gateway
            dev_in = DeviceCreate(
                floor_plan_id=None,
                name=f"Gateway {mac}",
                code=None,
                type="BLE_GATEWAY",
                mac_address=mac,
                description="Auto-registered from MQTT",
                pos_x=None,
                pos_y=None,
                last_seen_at=now,
            )
            db_device = await crud_device.create(db, dev_in)
            logger.info("Auto-registered new gateway device: %s", mac)
        else:
            await crud_device.update(db, db_device, {"last_seen_at": now})

        logger.debug(
            "Gateway heartbeat/detection: mac=%s last_seen_at=%s",
            mac,
            now.isoformat(),
        )
        return db_device

    # ------------------------------------------------------------------
    # Handlers de mensagem
    # ------------------------------------------------------------------

    async def _handle_gateway_heartbeat(self, topic: str, payload: bytes) -> None:
        """
        Auto-cadastra/atualiza Device para gateways que publicam
        em tópicos com o prefixo configurado, e atualiza last_seen_at.
        """
        gateway_id = self._extract_gateway_id_from_topic(topic)
        if not gateway_id:
            return

        async with self.session_factory() as db:
            await self._get_or_create_gateway(db, gateway_id)

    async def _handle_detection_message(self, topic: str, payload: bytes) -> None:
        """
        Trata mensagens de detecção (TAG vista por GATEWAY).

        Regras:
        - Se TAG não estiver cadastrada no banco -> IGNORA (cadastro manual).
        - Garante device do gateway (auto-cadastro).
        - Grava CollectionLog.
        - Dispara process_detection() para engine de alertas.
        """
        data = _decode_payload(payload)
        if data is None:
            return

        tag_mac = self._extract_tag_mac_from_data(data)
        if tag_mac is None:
            # sem tag não tem log de pessoa
            return

        gateway_mac = self._extract_gateway_mac_from_data(data, topic)
        if gateway_mac is None:
            logger.debug("Ignoring detection message without gateway_mac: %s", data)
            return

        rssi = self._extract_rssi_from_data(data)

        async with self.session_factory() as db:
            from app.crud import (
                tag as crud_tag,
                collection_log as crud_collection_log,
            )

            # TAG precisa estar cadastrada (regra de negócio)
            db_tag = await crud_tag.get_by_mac(db, mac_address=tag_mac)
            if not db_tag:
                logger.debug("Ignoring detection for unknown tag MAC: %s", tag_mac)
                return

            # garante gateway e atualiza last_seen_at
            db_device = await self._get_or_create_gateway(db, gateway_mac)

            # grava log
            raw_payload = json.dumps(data, ensure_ascii=False)

            log_in = CollectionLogCreate(
                device_id=db_device.id,
                tag_id=db_tag.id,
                rssi=rssi,
                raw_payload=raw_payload,
            )

            await crud_collection_log.create(db, log_in)
            logger.debug(
                "Created CollectionLog via MQTT: device_id=%s tag_id=%s rssi=%s",
                db_device.id,
                db_tag.id,
                rssi,
            )

            # dispara regras/eventos (webhooks, alertas, etc.)
            await process_detection(db, db_device, db_tag)

    async def handle_message(self, topic: str, payload: bytes) -> None:
        """
        Handler geral para cada mensagem vinda do broker.
        """
        logger.info("MQTT message received: topic=%s payload=%s", topic, payload)

        prefix = self.settings.MQTT_GATEWAY_TOPIC_PREFIX.rstrip("/")
        if topic.startswith(prefix):
            await self._handle_gateway_heartbeat(topic, payload)

        # tenta tratar como mensagem de detecção
        await self._handle_detection_message(topic, payload)

    # ------------------------------------------------------------------
    # Monitor de OFFLINE / ONLINE
    # ------------------------------------------------------------------

    async def _handle_gateway_offline(
        self,
        db,
        device: Device,
        now: datetime,
        offline_seconds: int,
    ) -> None:
        """
        Hook chamado quando detectamos transição ONLINE -> OFFLINE
        para um gateway.
        """
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
        """
        Hook chamado quando detectamos transição OFFLINE -> ONLINE.
        """
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
        """
        Loop periódico que verifica quais gateways BLE estão
        offline/online com base em last_seen_at e DEVICE_OFFLINE_THRESHOLD_SECONDS.
        """
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

                        # primeira vez: só guarda, não gera evento
                        if prev_status is None:
                            self._gateway_status_cache[dev.id] = is_online
                            continue

                        # ONLINE -> OFFLINE
                        if prev_status and not is_online:
                            if offline_seconds is not None:
                                await self._handle_gateway_offline(
                                    db,
                                    dev,
                                    now,
                                    offline_seconds,
                                )

                        # OFFLINE -> ONLINE
                        if (not prev_status) and is_online:
                            await self._handle_gateway_online(db, dev, now)

                        self._gateway_status_cache[dev.id] = is_online

            except Exception as e:
                logger.exception("Error while running gateway offline monitor: %s", e)

    # ------------------------------------------------------------------
    # Loop principal MQTT
    # ------------------------------------------------------------------

    async def _mqtt_loop(self) -> None:
        """
        Loop principal do ingestor MQTT com reconexão simples.
        """
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
                                logger.exception(
                                    "Error processing MQTT message: %s",
                                    e,
                                )

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
        """
        Entry point chamado no startup da aplicação.

        Roda em paralelo:
        - loop MQTT (_mqtt_loop)
        - monitor de offline (_offline_monitor_loop)
        """
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
            # cancelamento vindo do shutdown do FastAPI
            self._stopped = True
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            self._stopped = True

    def stop(self) -> None:
        """
        Sinaliza para os loops internos pararem assim que possível.
        """
        self._stopped = True
