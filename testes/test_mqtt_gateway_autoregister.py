import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal, init_db
from app.models.device import Device
from app.services.mqtt_ingestor import MqttIngestor


@pytest.mark.asyncio
async def test_mqtt_gateway_autoregister_and_last_seen():
    await init_db()
    ingestor = MqttIngestor(settings, AsyncSessionLocal)

    topic = settings.MQTT_GATEWAY_TOPIC_PREFIX.rstrip("/") + "/AA:BB:CC:DD:EE:FF/heartbeat"
    payload = b"{}"  # conteúdo não importa para o heartbeat

    # chama o handler
    await ingestor.handle_message(topic, payload)

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Device).where(Device.mac_address == "AA:BB:CC:DD:EE:FF"))
        device = res.scalars().first()

        assert device is not None
        assert device.name.startswith("Gateway")
        assert device.last_seen_at is not None
