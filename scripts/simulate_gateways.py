# scripts/simulate_gateways.py

import asyncio
import json
import os
from datetime import datetime, timezone

from asyncio_mqtt import Client

# Usa as mesmas variáveis do backend, quando existirem
BROKER_HOST = os.getenv("RTLS_MQTT_HOST", os.getenv("MQTT_HOST", "localhost"))
BROKER_PORT = int(os.getenv("RTLS_MQTT_PORT", os.getenv("MQTT_PORT", "1883")))

# Mesmo tópico base do backend: rtls/gateways/#  -> base = rtls/gateways
BASE_TOPIC = os.getenv("RTLS_MQTT_TOPIC", "rtls/gateways/#")
if BASE_TOPIC.endswith("/#"):
    BASE_TOPIC = BASE_TOPIC[:-2]

# --------------------------------------------------------------------
# GATEWAYS E TAGS (BEACONS)
# --------------------------------------------------------------------

# Agora 5 gateways
GATEWAYS = [
    {"mac": "AA:BB:CC:DD:EE:01"},
    {"mac": "AA:BB:CC:DD:EE:02"},
    {"mac": "AA:BB:CC:DD:EE:03"},
    {"mac": "AA:BB:CC:DD:EE:04"},
    {"mac": "AA:BB:CC:DD:EE:05"},
]

# 4 TAGs (beacons) - todas precisam estar cadastradas no sistema
BEACONS = [
    {"mac": "11:22:33:44:55:66"},  # TAG original
    {"mac": "11:22:33:44:55:77"},
    {"mac": "11:22:33:44:55:88"},
    {"mac": "11:22:33:44:55:99"},
]

# Intervalo de rodízio: a cada 5 minutos (300s) cada TAG muda para o próximo gateway
ROTATION_INTERVAL_SECONDS = 5 * 60  # 300s


async def publish_status(client: Client) -> None:
    """
    Envia heartbeats dos gateways:
      rtls/gateways/<MAC>/heartbeat
    """
    while True:
        now = datetime.now(timezone.utc).isoformat()
        for gw in GATEWAYS:
            topic = f"{BASE_TOPIC}/{gw['mac']}/heartbeat"
            payload = {
                "gateway_mac": gw["mac"],
                "timestamp": now,
                "online": True,
            }
            print("PUB HEARTBEAT:", topic, payload)
            await client.publish(topic, json.dumps(payload))
        # Heartbeat a cada 10s
        await asyncio.sleep(10)


async def publish_detections(client: Client) -> None:
    """
    Envia detecções de TAG:
      rtls/gateways/<MAC>/detection

    LÓGICA DE RODÍZIO:
    - Temos N gateways e M beacons.
    - A cada ROTATION_INTERVAL_SECONDS (5 min), aumentamos o índice de "rodízio".
    - A posição atual de cada beacon é:
        gateway_index = (beacon_index + rotation_index) % len(GATEWAYS)

      Ou seja, a cada 5 minutos cada pessoa "anda" para o próximo gateway.
    """

    rssi_values = [-60, -68, -75, -80]
    start = datetime.now(timezone.utc)
    rssi_index = 0

    while True:
        now = datetime.now(timezone.utc)
        elapsed_seconds = (now - start).total_seconds()
        rotation_index = int(elapsed_seconds // ROTATION_INTERVAL_SECONDS)

        # Para cada beacon, decide em qual gateway ele está neste momento
        for beacon_idx, beacon in enumerate(BEACONS):
            gw_index = (beacon_idx + rotation_index) % len(GATEWAYS)
            gw = GATEWAYS[gw_index]

            rssi = rssi_values[rssi_index % len(rssi_values)]
            rssi_index += 1

            topic = f"{BASE_TOPIC}/{gw['mac']}/detection"
            payload = {
                "gateway_mac": gw["mac"],
                "tag_mac": beacon["mac"],
                "rssi": rssi,
                "timestamp": now.isoformat(),
            }
            print("PUB DETECTION:", topic, payload)
            await client.publish(topic, json.dumps(payload))

        # Entre uma leitura e outra (pensa como "scan" a cada 5s)
        await asyncio.sleep(5)


async def main() -> None:
    async with Client(BROKER_HOST, BROKER_PORT) as client:
        await asyncio.gather(
            publish_status(client),
            publish_detections(client),
        )


if __name__ == "__main__":
    asyncio.run(main())
