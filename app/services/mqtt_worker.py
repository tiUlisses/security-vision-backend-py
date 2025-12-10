# app/services/mqtt_worker.py
import asyncio

from asyncio_mqtt import Client

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.mqtt_gateways import handle_gateway_message


async def mqtt_main_worker() -> None:
    """
    Worker principal do MQTT, chamado no startup do FastAPI.
    """
    async with Client(
        hostname=settings.MQTT_HOST,
        port=settings.MQTT_PORT,
        username=settings.MQTT_USERNAME,
        password=settings.MQTT_PASSWORD,
    ) as client:
        # aqui você pode assinar outros tópicos (se tiver) além dos gateways
        await client.subscribe(f"{settings.MQTT_GATEWAY_TOPIC_PREFIX}/#")

        async with client.unfiltered_messages() as messages:
            async for message in messages:
                # para cada mensagem, abrimos uma sessão rápida só pra tratar
                async with AsyncSessionLocal() as db:
                    await handle_gateway_message(
                        db=db,
                        topic=message.topic,
                        payload=message.payload,
                    )


def start_mqtt_background_task(loop: asyncio.AbstractEventLoop) -> None:
    loop.create_task(mqtt_main_worker())
