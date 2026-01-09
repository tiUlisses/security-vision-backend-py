# app/api/routes/buildings.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.crud import building as crud_building
from app.crud import floor_plan as crud_floor_plan  # <--- IMPORT IMPORTANTE
from app.schemas import BuildingCreate, BuildingRead, BuildingUpdate, FloorPlanRead

# 🔔 dispatcher genérico de webhooks (mesmo que usamos em devices/people/tags)
from app.services.webhook_dispatcher import dispatch_generic_webhook
from app.services.access_control_projection import publish_projection_for_building

router = APIRouter()


@router.get("/", response_model=List[BuildingRead])
async def list_buildings(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db_session),
):
    return await crud_building.get_multi(db, skip=skip, limit=limit)


@router.post(
    "/",
    response_model=BuildingRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_building(
    building_in: BuildingCreate,
    db: AsyncSession = Depends(get_db_session),
):
    # poderia validar unicidade de code aqui se quiser tratar erro customizado
    building = await crud_building.create(db, building_in)

    # 🔔 Webhook: BUILDING_CREATED
    created_at = getattr(building, "created_at", None)
    label = (
        getattr(building, "name", None)
        or getattr(building, "code", None)
        or f"Building {building.id}"
    )

    await dispatch_generic_webhook(
        db,
        event_type="BUILDING_CREATED",
        payload={
            "building_id": building.id,
            "name": getattr(building, "name", None),
            "code": getattr(building, "code", None),
            "label": label,
            "created_at": created_at.isoformat() if created_at else None,
        },
    )

    await publish_projection_for_building(db, building)

    return building


# 👇 NOVO: buscar prédio pelo code (ex: PredioA)
@router.get("/by-code/{code}", response_model=BuildingRead)
async def get_building_by_code(
    code: str,
    db: AsyncSession = Depends(get_db_session),
):
    db_building = await crud_building.get_by_code(db, code=code)
    if not db_building:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Building not found",
        )
    return db_building


@router.get("/{building_id}", response_model=BuildingRead)
async def get_building(
    building_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    db_building = await crud_building.get(db, id=building_id)
    if not db_building:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Building not found",
        )
    return db_building


@router.put("/{building_id}", response_model=BuildingRead)
async def update_building(
    building_id: int,
    building_in: BuildingUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    db_building = await crud_building.get(db, id=building_id)
    if not db_building:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Building not found",
        )

    updated = await crud_building.update(db, db_building, building_in)

    # 🔔 Webhook: BUILDING_UPDATED
    updated_at = getattr(updated, "updated_at", None)
    label = (
        getattr(updated, "name", None)
        or getattr(updated, "code", None)
        or f"Building {updated.id}"
    )

    await dispatch_generic_webhook(
        db,
        event_type="BUILDING_UPDATED",
        payload={
            "building_id": updated.id,
            "name": getattr(updated, "name", None),
            "code": getattr(updated, "code", None),
            "label": label,
            "updated_at": updated_at.isoformat() if updated_at else None,
        },
    )

    await publish_projection_for_building(db, updated)

    return updated


@router.delete(
    "/{building_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_building(
    building_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    deleted = await crud_building.remove(db, id=building_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Building not found",
        )

    # 🔔 Webhook: BUILDING_DELETED
    label = (
        getattr(deleted, "name", None)
        or getattr(deleted, "code", None)
        or f"Building {building_id}"
    )

    await dispatch_generic_webhook(
        db,
        event_type="BUILDING_DELETED",
        payload={
            "building_id": building_id,
            "name": getattr(deleted, "name", None),
            "code": getattr(deleted, "code", None),
            "label": label,
        },
    )

    # 204 -> sem body
    return None


@router.get("/{building_id}/floor-plans", response_model=List[FloorPlanRead])
async def list_building_floor_plans(
    building_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    # Garante que o prédio existe
    building = await crud_building.get(db, id=building_id)
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    # Busca as plantas (andares) ligadas a esse prédio
    floor_plans = await crud_floor_plan.get_multi_by_building(
        db, building_id=building_id
    )
    return floor_plans
