# app/api/routes/alert_rules.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.crud.alert_rule import alert_rule as crud_alert_rule
from app.schemas.alert_rule import (
    AlertRuleCreate,
    AlertRuleRead,
    AlertRuleUpdate,
)

# 🔔 dispatcher genérico de webhooks
from app.services.webhook_dispatcher import dispatch_generic_webhook

router = APIRouter()


@router.get("/", response_model=List[AlertRuleRead])
async def list_alert_rules(
    skip: int = 0,
    limit: int = 100,
    rule_type: str | None = Query(default=None),
    group_id: int | None = Query(default=None),
    device_id: int | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    create_incident: bool | None = Query(default=None),
):
    rules = await crud_alert_rule.get_multi(db, skip=skip, limit=limit)

    if create_incident is not None:
        rules = [r for r in rules if getattr(r, "create_incident", False) == create_incident]
    if rule_type is not None:
        rules = [r for r in rules if r.rule_type == rule_type]
    if group_id is not None:
        rules = [r for r in rules if r.group_id == group_id]
    if device_id is not None:
        rules = [r for r in rules if r.device_id == device_id]
    if is_active is not None:
        rules = [r for r in rules if r.is_active == is_active]

    return rules


@router.post(
    "/",
    response_model=AlertRuleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_alert_rule(
    rule_in: AlertRuleCreate,
    db: AsyncSession = Depends(get_db_session),
):
    rule = await crud_alert_rule.create(db, rule_in)

    # 🔔 Webhook: ALERT_RULE_CREATED
    created_at = getattr(rule, "created_at", None)

    await dispatch_generic_webhook(
        db,
        event_type="ALERT_RULE_CREATED",
        payload={
            "create_incident": getattr(rule, "create_incident", False),
            "incident_kind": getattr(rule, "incident_kind", None),
            "incident_severity": getattr(rule, "incident_severity", None),
            "incident_title_template": getattr(rule, "incident_title_template", None),
            "incident_description_template": getattr(rule, "incident_description_template", None),
            "incident_sla_minutes": getattr(rule, "incident_sla_minutes", None),
            "incident_assigned_group_id": getattr(rule, "incident_assigned_group_id", None),
            "incident_assigned_to_user_id": getattr(rule, "incident_assigned_to_user_id", None),
            "incident_auto_close_on_end": getattr(rule, "incident_auto_close_on_end", False),
        },
    )

    return rule


@router.get("/{rule_id}", response_model=AlertRuleRead)
async def get_alert_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_alert_rule.get(db, id=rule_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return db_obj


@router.put("/{rule_id}", response_model=AlertRuleRead)
async def update_alert_rule(
    rule_id: int,
    rule_in: AlertRuleUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_alert_rule.get(db, id=rule_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    updated = await crud_alert_rule.update(db, db_obj, rule_in)

    # 🔔 Webhook: ALERT_RULE_UPDATED
    updated_at = getattr(updated, "updated_at", None)

    await dispatch_generic_webhook(
        db,
        event_type="ALERT_RULE_UPDATED",
        payload={
            "rule_id": updated.id,
            "name": updated.name,
            "description": updated.description,
            "rule_type": updated.rule_type,
            "group_id": updated.group_id,
            "device_id": updated.device_id,
            "max_dwell_seconds": updated.max_dwell_seconds,
            "is_active": updated.is_active,
            "updated_at": updated_at.isoformat() if updated_at else None,
        },
    )

    return updated


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    deleted = await crud_alert_rule.remove(db, id=rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    # 🔔 Webhook: ALERT_RULE_DELETED
    await dispatch_generic_webhook(
        db,
        event_type="ALERT_RULE_DELETED",
        payload={
            "rule_id": rule_id,
            "name": getattr(deleted, "name", None),
            "description": getattr(deleted, "description", None),
            "rule_type": getattr(deleted, "rule_type", None),
            "group_id": getattr(deleted, "group_id", None),
            "device_id": getattr(deleted, "device_id", None),
        },
    )

    return None
