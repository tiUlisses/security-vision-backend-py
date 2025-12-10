# app/api/routes/tags.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.crud import tag as crud_tag
from app.schemas import TagCreate, TagRead, TagUpdate

# 🔔 dispatcher genérico de webhooks
from app.services.webhook_dispatcher import dispatch_generic_webhook

router = APIRouter()


@router.get("/", response_model=List[TagRead])
async def list_tags(
    skip: int = 0,
    limit: int = 100,
    person_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    tags = await crud_tag.get_multi(db, skip=skip, limit=limit)
    if person_id is not None:
        tags = [t for t in tags if t.person_id == person_id]
    return tags


@router.get("/by-mac/{mac_address}", response_model=TagRead)
async def get_tag_by_mac(
    mac_address: str,
    db: AsyncSession = Depends(get_db_session),
):
    db_tag = await crud_tag.get_by_mac(db, mac_address=mac_address)
    if not db_tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return db_tag


@router.post(
    "/",
    response_model=TagRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_tag(
    tag_in: TagCreate,
    db: AsyncSession = Depends(get_db_session),
):
    tag = await crud_tag.create(db, tag_in)

    # 🔔 Webhook: TAG_CREATED
    created_at = getattr(tag, "created_at", None)
    label = getattr(tag, "code", None) or getattr(tag, "mac_address", None)

    await dispatch_generic_webhook(
        db,
        event_type="TAG_CREATED",
        payload={
            "tag_id": tag.id,
            "code": getattr(tag, "code", None),
            "mac_address": getattr(tag, "mac_address", None),
            "person_id": getattr(tag, "person_id", None),
            "label": label,
            "created_at": created_at.isoformat() if created_at else None,
        },
    )

    return tag


@router.get("/{tag_id}", response_model=TagRead)
async def get_tag(
    tag_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_tag.get(db, id=tag_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Tag not found")
    return db_obj


@router.put("/{tag_id}", response_model=TagRead)
async def update_tag(
    tag_id: int,
    tag_in: TagUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_tag.get(db, id=tag_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Tag not found")

    updated = await crud_tag.update(db, db_obj, tag_in)

    # 🔔 Webhook: TAG_UPDATED
    updated_at = getattr(updated, "updated_at", None)
    label = getattr(updated, "code", None) or getattr(updated, "mac_address", None)

    await dispatch_generic_webhook(
        db,
        event_type="TAG_UPDATED",
        payload={
            "tag_id": updated.id,
            "code": getattr(updated, "code", None),
            "mac_address": getattr(updated, "mac_address", None),
            "person_id": getattr(updated, "person_id", None),
            "label": label,
            "updated_at": updated_at.isoformat() if updated_at else None,
        },
    )

    return updated


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    deleted = await crud_tag.remove(db, id=tag_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tag not found")

    # 🔔 Webhook: TAG_DELETED
    label = getattr(deleted, "code", None) or getattr(deleted, "mac_address", None)

    await dispatch_generic_webhook(
        db,
        event_type="TAG_DELETED",
        payload={
            "tag_id": deleted.id,
            "code": getattr(deleted, "code", None),
            "mac_address": getattr(deleted, "mac_address", None),
            "person_id": getattr(deleted, "person_id", None),
            "label": label,
        },
    )

    return None
