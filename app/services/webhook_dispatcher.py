# app/services/webhook_dispatcher.py

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Iterable, List, Dict, Any

import httpx
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook_subscription import WebhookSubscription
from app.models.alert_event import AlertEvent

logger = logging.getLogger("rtls.webhooks")


def _build_envelope(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
  """
  Envelope padrão de webhook que será enviado para os assinantes.
  """
  return {
    "event_type": event_type,
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "payload": payload,
  }


async def _load_subscriptions(
  db: AsyncSession,
  event_type: str,
) -> List[WebhookSubscription]:
  """
  Busca os webhooks ativos cujo event_type_filter é:
    - NULL  -> recebe todos os eventos
    - IGUAL -> recebe apenas esse tipo de evento
  """
  stmt = (
    select(WebhookSubscription)
    .where(WebhookSubscription.is_active.is_(True))
    .where(
      or_(
        WebhookSubscription.event_type_filter.is_(None),
        WebhookSubscription.event_type_filter == event_type,
      )
    )
  )

  res = await db.execute(stmt)
  subs = list(res.scalars().all())
  return subs


async def _send_to_subscribers(
  subs: Iterable[WebhookSubscription],
  envelope: Dict[str, Any],
) -> None:
  """
  Envia o envelope JSON para cada assinatura.
  Erros de rede NÃO derrubam a requisição da API – apenas logam.
  """
  subs = list(subs)
  if not subs:
    return

  body = json.dumps(envelope, ensure_ascii=False).encode("utf-8")

  async with httpx.AsyncClient(timeout=10) as client:
    for sub in subs:
      headers = {
        "Content-Type": "application/json",
        "X-SV-Webhook-Id": str(sub.id),
        "X-SV-Event-Type": envelope["event_type"],
      }

      # Assinatura opcional com secret_token
      if sub.secret_token:
        signature = hmac.new(
          sub.secret_token.encode("utf-8"),
          body,
          hashlib.sha256,
        ).hexdigest()
        headers["X-SV-Signature"] = f"sha256={signature}"

      try:
        resp = await client.post(sub.url, content=body, headers=headers)
        if resp.status_code >= 400:
          logger.warning(
            "Webhook %s (%s) respondeu status %s",
            sub.id,
            sub.url,
            resp.status_code,
          )
      except Exception as exc:  # noqa: BLE001
        logger.exception(
          "Falha ao enviar webhook %s (%s): %s",
          sub.id,
          sub.url,
          exc,
        )


# ---------------------------------------------------------------------------
# 1) Uso genérico (devices, people, tags, buildings, etc.)
# ---------------------------------------------------------------------------

async def dispatch_generic_webhook(
  db: AsyncSession,
  *,
  event_type: str,
  payload: Dict[str, Any],
) -> None:
  """
  Dispara webhooks genéricos de CRUD:
    - DEVICE_CREATED, DEVICE_UPDATED, DEVICE_DELETED, ...
    - PERSON_CREATED, TAG_CREATED, etc.

  event_type_filter da assinatura deve bater com event_type,
  ou estar NULL para receber tudo.
  """
  envelope = _build_envelope(event_type, payload)
  subs = await _load_subscriptions(db, event_type)
  await _send_to_subscribers(subs, envelope)


# ---------------------------------------------------------------------------
# 2) Uso específico do AlertEngine (AlertEvent)
# ---------------------------------------------------------------------------

async def dispatch_webhooks(
  db: AsyncSession,
  alert_event: AlertEvent,
) -> None:
  """
  Compatível com AlertEngine: recebe um AlertEvent e dispara webhooks
  baseados em alert_event.event_type (FORBIDDEN_SECTOR, DWELL_TIME,
  GATEWAY_OFFLINE, GATEWAY_ONLINE, etc.).
  """
  # Tenta aproveitar o payload JSON já salvo no banco
  base_payload: Dict[str, Any] = {}
  if alert_event.payload:
    try:
      base_payload = json.loads(alert_event.payload)
    except json.JSONDecodeError:
      base_payload = {"raw_payload": alert_event.payload}

  payload: Dict[str, Any] = {
    **base_payload,
    "alert_event_id": alert_event.id,
    "event_type": alert_event.event_type,
    "message": alert_event.message,
    "rule_id": alert_event.rule_id,
    "device_id": alert_event.device_id,
    "tag_id": alert_event.tag_id,
    "person_id": alert_event.person_id,
    "building_id": alert_event.building_id,
    "floor_id": alert_event.floor_id,
    "floor_plan_id": alert_event.floor_plan_id,
    "started_at": alert_event.started_at.isoformat()
    if alert_event.started_at
    else None,
    "last_seen_at": alert_event.last_seen_at.isoformat()
    if alert_event.last_seen_at
    else None,
    "ended_at": alert_event.ended_at.isoformat()
    if alert_event.ended_at
    else None,
    "is_open": alert_event.is_open,
  }

  envelope = _build_envelope(alert_event.event_type, payload)
  subs = await _load_subscriptions(db, alert_event.event_type)
  await _send_to_subscribers(subs, envelope)
