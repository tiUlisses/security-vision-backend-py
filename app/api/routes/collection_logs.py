# app/api/routes/collection_logs.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.crud import collection_log as crud_collection_log
from app.crud import device as crud_device
from app.crud import tag as crud_tag
from app.schemas import (
    CollectionLogCreate,
    CollectionLogRead,
    CollectionLogUpdate,
)
from app.services.alert_engine import process_detection

# 🔹 ESTE É O router QUE O FastAPI PROCURA
router = APIRouter()


@router.get("/", response_model=List[CollectionLogRead])
async def list_collection_logs(
    skip: int = 0,
    limit: int = 100,
    device_id: int | None = Query(default=None),
    tag_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    logs = await crud_collection_log.get_multi(db, skip=skip, limit=limit)
    if device_id is not None:
        logs = [l for l in logs if l.device_id == device_id]
    if tag_id is not None:
        logs = [l for l in logs if l.tag_id == tag_id]
    return logs


@router.post(
    "/",
    response_model=CollectionLogRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_collection_log(
    log_in: CollectionLogCreate,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Cria um log de coleta e, em seguida, aciona o motor de alertas.

    Isso garante que as regras FORBIDDEN_SECTOR / DWELL_TIME sejam
    avaliadas sempre que um novo CollectionLog é inserido via API.
    """
    # 1) cria o log normalmente
    log = await crud_collection_log.create(db, log_in)

    # 2) carrega Device e Tag relacionados
    device = await crud_device.get(db, id=log.device_id) if log.device_id else None
    tag = await crud_tag.get(db, id=log.tag_id) if log.tag_id else None

    # 3) processa alertas se ambos existirem
    if device and tag:
        # 👈 AQUI É O PULO DO GATO: passamos o log
        await process_detection(db, device=device, tag=tag, log=log)

    return log


@router.get("/{log_id}", response_model=CollectionLogRead)
async def get_collection_log(
    log_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_collection_log.get(db, id=log_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Collection log not found")
    return db_obj


@router.put("/{log_id}", response_model=CollectionLogRead)
async def update_collection_log(
    log_id: int,
    log_in: CollectionLogUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_collection_log.get(db, id=log_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Collection log not found")
    return await crud_collection_log.update(db, db_obj, log_in)


@router.delete("/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection_log(
    log_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    deleted = await crud_collection_log.remove(db, id=log_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Collection log not found")
    return None
