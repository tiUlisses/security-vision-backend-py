# app/services/mqtt_gateways.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud import device as crud_device
from app.crud import tag as crud_tag
from app.models.collection_log import CollectionLog


def _parse_gateway_topic(topic: str) -> Tuple[str | None, Literal["status", "beacon"] | None]:
    """
    topic esperado: "<prefix>/<gateway_mac>/status" ou "beacon"
    ex: "rtls/gateways/AA:BB:CC:DD:EE:01/status"
    """
    prefix = settings.MQTT_GATEWAY_TOPIC_PREFIX.rstrip("/")
    if not topic.startswith(prefix + "/"):
        return None, None

    rest = topic[len(prefix) + 1 :]  # parte depois do prefix/
    parts = rest.split("/")
    if len(parts) < 2:
        return None, None

    gateway_mac = parts[0]
    suffix = parts[1]

    if suffix == "status":
        return gateway_mac, "status"
    if suffix == "beacon":
        return gateway_mac, "beacon"

    return gateway_mac, None


async def handle_gateway_message(
    db: AsyncSession,
    topic: str,
    payload: bytes,
) -> None:
    """
    Lida com mensagens de gateways (status + beacons).

    - Auto-cadastra gateways desconhecidos
    - Atualiza last_seen_at
    - Cria CollectionLog SOMENTE para tags cadastradas
    """
    gateway_mac, msg_type = _parse_gateway_topic(topic)
    if not gateway_mac or not msg_type:
        return

    try:
        data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError:
        # aqui daria pra logar warning, mas não vamos explodir a app
        return

    # garante que o gateway existe
    device = await crud_device.get_or_create_gateway_by_mac(db, gateway_mac)

    # atualiza last_seen_at sempre que receber algo do gateway
    now = datetime.now(timezone.utc)
    device.last_seen_at = now
    db.add(device)

    if msg_type == "status":
        # por enquanto, só usamos para last_seen_at; no futuro dá pra salvar battery, etc.
        await db.commit()
        return

    if msg_type == "beacon":
        readings = data.get("readings") or []
        if not isinstance(readings, list):
            readings = []

        for r in readings:
            # tolerante a variações no campo do MAC da tag
            tag_mac = (
                r.get("tag_mac")
                or r.get("mac")
                or r.get("tag")
                or r.get("tagMac")
            )
            if not tag_mac:
                continue

            tag = await crud_tag.get_by_mac(db, tag_mac)
            if not tag or not tag.active:
                # regra que definimos: IGNORAR tags que não estão cadastradas
                continue

            rssi = r.get("rssi")
            log = CollectionLog(
                device_id=device.id,
                tag_id=tag.id,
                rssi=rssi,
                raw_payload=r,  # nosso campo JSONB pode receber dict direto
            )
            db.add(log)

        await db.commit()
