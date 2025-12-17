# app/api/routes/incident_rules.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_active_user
from app.models.user import User
from app.schemas import (
    IncidentRuleCreate,
    IncidentRuleRead,
    IncidentRuleUpdate,
)
from app.crud import incident_rule as crud_incident_rule

router = APIRouter()


@router.get("/", response_model=List[IncidentRuleRead])
async def list_incident_rules(
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    return await crud_incident_rule.get_multi(db)


@router.post(
    "/",
    response_model=IncidentRuleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_incident_rule(
    rule_in: IncidentRuleCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    rule = await crud_incident_rule.create(db, obj_in=rule_in)
    return rule


@router.get("/{rule_id}", response_model=IncidentRuleRead)
async def get_incident_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    rule = await crud_incident_rule.get(db, id=rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="IncidentRule not found")
    return rule


@router.patch("/{rule_id}", response_model=IncidentRuleRead)
async def update_incident_rule(
    rule_id: int,
    rule_in: IncidentRuleUpdate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    db_rule = await crud_incident_rule.get(db, id=rule_id)
    if not db_rule:
        raise HTTPException(status_code=404, detail="IncidentRule not found")

    rule = await crud_incident_rule.update(db, db_obj=db_rule, obj_in=rule_in)
    return rule


@router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_incident_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    db_rule = await crud_incident_rule.get(db, id=rule_id)
    if not db_rule:
        raise HTTPException(status_code=404, detail="IncidentRule not found")

    await crud_incident_rule.remove(db, id=rule_id)
    return None
