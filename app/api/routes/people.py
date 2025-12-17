from typing import List
from datetime import timezone, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.crud import (
    person as crud_person,
    tag as crud_tag,
    collection_log as crud_collection_log,
    device as crud_device,
    floor_plan as crud_floor_plan,
    floor as crud_floor,
    building as crud_building,
)
from app.schemas import PersonCreate, PersonRead, PersonUpdate
from app.schemas.location import PersonCurrentLocation

# ⬇️ NOVO: dispatcher genérico de webhooks
from app.services.webhook_dispatcher import dispatch_generic_webhook

router = APIRouter()


@router.get("/", response_model=List[PersonRead])
async def list_people(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db_session),
):
    return await crud_person.get_multi(db, skip=skip, limit=limit)


@router.post(
    "/",
    response_model=PersonRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_person(
    person_in: PersonCreate,
    db: AsyncSession = Depends(get_db_session),
):
    person = await crud_person.create(db, person_in)

    # 🔔 Webhook: PERSON_CREATED
    full_name = getattr(person, "full_name", None) or getattr(person, "name", None)
    created_at = getattr(person, "created_at", None)

    await dispatch_generic_webhook(
        db,
        event_type="PERSON_CREATED",
        payload={
            "person_id": person.id,
            "full_name": full_name,
            "created_at": created_at.isoformat() if created_at else None,
        },
    )

    return person


@router.get("/{person_id}", response_model=PersonRead)
async def get_person(
    person_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_person.get(db, id=person_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Person not found")
    return db_obj


@router.put("/{person_id}", response_model=PersonRead)
async def update_person(
    person_id: int,
    person_in: PersonUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_person.get(db, id=person_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Person not found")

    updated = await crud_person.update(db, db_obj, person_in)

    # 🔔 Webhook: PERSON_UPDATED
    full_name = getattr(updated, "full_name", None) or getattr(updated, "name", None)
    updated_at = getattr(updated, "updated_at", None)

    await dispatch_generic_webhook(
        db,
        event_type="PERSON_UPDATED",
        payload={
            "person_id": updated.id,
            "full_name": full_name,
            "updated_at": updated_at.isoformat() if updated_at else None,
        },
    )

    return updated


@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(
    person_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    deleted = await crud_person.remove(db, id=person_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Person not found")

    # 🔔 Webhook: PERSON_DELETED
    full_name = getattr(deleted, "full_name", None) or getattr(deleted, "name", None)

    await dispatch_generic_webhook(
        db,
        event_type="PERSON_DELETED",
        payload={
            "person_id": deleted.id,
            "full_name": full_name,
        },
    )

    return None


@router.get("/{person_id}/current-location", response_model=PersonCurrentLocation)
async def get_person_current_location(
    person_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    # 1) Garantir que a pessoa existe
    person = await crud_person.get(db, id=person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    # 2) Pegar TAGs associadas à pessoa
    tags = await crud_tag.get_by_person(db, person_id=person_id)
    if not tags:
        raise HTTPException(
            status_code=404,
            detail="No tags associated with this person",
        )

    # 3) Descobrir a última leitura dentre todas as TAGs
    best_log = None
    best_tag = None

    for t in tags:
        log = await crud_collection_log.get_last_for_tag(db, tag_id=t.id)
        if not log:
            continue
        if best_log is None or log.created_at > best_log.created_at:
            best_log = log
            best_tag = t

    if not best_log or not best_tag:
        raise HTTPException(
            status_code=404,
            detail="No collection logs found for this person's tags",
        )

    # 4) Resolver device → floor_plan → floor → building
    device = await crud_device.get(db, id=best_log.device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found for last collection log")

    floor_plan = await crud_floor_plan.get(db, id=device.floor_plan_id)
    if not floor_plan:
        raise HTTPException(status_code=404, detail="Floor plan not found")

    floor = await crud_floor.get(db, id=floor_plan.floor_id)
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")

    building = await crud_building.get(db, id=floor.building_id)
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    return PersonCurrentLocation(
        person_id=person.id,
        person_full_name=person.full_name,
        tag_id=best_tag.id,
        tag_mac_address=best_tag.mac_address,
        device_id=device.id,
        device_name=device.name,
        device_mac_address=device.mac_address,
        device_pos_x=device.pos_x,
        device_pos_y=device.pos_y,
        floor_plan_id=floor_plan.id,
        floor_plan_name=floor_plan.name,
        floor_plan_image_url=floor_plan.image_url,
        floor_id=field.id,
        floor_name=floor.name,
        building_id=building.id,
        building_name=building.name,
        last_seen_at=best_log.created_at,
    )
