import json

import pytest
from sqlalchemy import select, delete

from app.core.config import settings
from app.db.session import AsyncSessionLocal, init_db
from app.models.collection_log import CollectionLog
from app.services.mqtt_ingestor import MqttIngestor
from app.crud import tag as crud_tag, device as crud_device
from app.schemas import TagCreate, DeviceCreate


@pytest.mark.asyncio
async def test_mqtt_ingestor_stores_log_only_for_known_tag():
    await init_db()

    ingestor = MqttIngestor(settings, AsyncSessionLocal)

    async with AsyncSessionLocal() as db:
        # limpa logs antes
        await db.execute(delete(CollectionLog))
        await db.commit()

        # cria Device e Tag conhecidos
        dev_in = DeviceCreate(
            floor_plan_id=1,  # cuidado: precisa existir uma floor_plan id=1 ou ajustar o teste
            name="GW Teste",
            code="GW_TEST",
            type="BLE_GATEWAY",
            mac_address="11:22:33:44:55:66",
            description="Gateway teste",
            pos_x=10.0,
            pos_y=20.0,
        )
        device = await crud_device.create(db, dev_in)

        tag_in = TagCreate(
            mac_address="AA:BB:CC:DD:EE:FF",
            label="Tag Teste",
            person_id=None,
            active=True,
            notes=None,
        )
        tag = await crud_tag.create(db, tag_in)

        # mensagem com TAG conhecida
        msg_known = {
            "gateway_mac": device.mac_address,
            "tag_mac": tag.mac_address,
            "rssi": -70,
        }

    # chama o ingestor fora do contexto da sessão
    await ingestor.process_message(json.dumps(msg_known).encode("utf-8"))

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(CollectionLog))
        logs = res.scalars().all()
        assert len(logs) == 1
        assert logs[0].tag_id == tag.id
        assert logs[0].device_id == device.id

        # limpa para o próximo teste
        await db.execute(delete(CollectionLog))
        await db.commit()


@pytest.mark.asyncio
async def test_mqtt_ingestor_ignores_unknown_tag():
    await init_db()

    ingestor = MqttIngestor(settings, AsyncSessionLocal)

    async with AsyncSessionLocal() as db:
        # limpa logs
        await db.execute(delete(CollectionLog))
        await db.commit()

        # cria apenas o Device (sem Tag)
        dev_in = DeviceCreate(
            floor_plan_id=1,  # mesma observação do teste anterior
            name="GW Teste 2",
            code="GW_TEST_2",
            type="BLE_GATEWAY",
            mac_address="22:33:44:55:66:77",
            description="Gateway teste 2",
            pos_x=30.0,
            pos_y=40.0,
        )
        device = await crud_device.create(db, dev_in)

    # mensagem com TAG NÃO cadastrada
    msg_unknown_tag = {
        "gateway_mac": device.mac_address,
        "tag_mac": "FF:EE:DD:CC:BB:AA",
        "rssi": -60,
    }

    await ingestor.process_message(json.dumps(msg_unknown_tag).encode("utf-8"))

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(CollectionLog))
        logs = res.scalars().all()
        # como a TAG não existe, NÃO deve ter log
        assert len(logs) == 0
