from typing import List
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    UploadFile,
    File,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.config import settings
from app.crud import floor_plan as crud_floor_plan
from app.crud import device as crud_device
from app.schemas import (
    FloorPlanCreate,
    FloorPlanRead,
    FloorPlanUpdate,
    DeviceRead,
)

router = APIRouter()


@router.get("/", response_model=List[FloorPlanRead])
async def list_floor_plans(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db_session),
):
    return await crud_floor_plan.get_multi(db, skip=skip, limit=limit)


@router.post(
    "/",
    response_model=FloorPlanRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_floor_plan(
    floor_plan_in: FloorPlanCreate,
    db: AsyncSession = Depends(get_db_session),
):
    return await crud_floor_plan.create(db, floor_plan_in)


@router.get("/{floor_plan_id}", response_model=FloorPlanRead)
async def get_floor_plan(
    floor_plan_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_floor_plan.get(db, id=floor_plan_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Floor plan not found")
    return db_obj


@router.put("/{floor_plan_id}", response_model=FloorPlanRead)
async def update_floor_plan(
    floor_plan_id: int,
    floor_plan_in: FloorPlanUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_floor_plan.get(db, id=floor_plan_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Floor plan not found")
    return await crud_floor_plan.update(db, db_obj, floor_plan_in)


@router.delete("/{floor_plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_floor_plan(
    floor_plan_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    deleted = await crud_floor_plan.remove(db, id=floor_plan_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Floor plan not found")
    return None


@router.get("/{floor_plan_id}/devices", response_model=List[DeviceRead])
async def list_floor_plan_devices(
    floor_plan_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    # garante que a planta existe
    fp = await crud_floor_plan.get(db, id=floor_plan_id)
    if not fp:
        raise HTTPException(status_code=404, detail="Floor plan not found")

    # pega todos devices e filtra por floor_plan_id (MVP)
    devices = await crud_device.get_multi(db)
    devices = [d for d in devices if d.floor_plan_id == floor_plan_id]
    return devices


# ---------- NOVO: upload de imagem da planta ----------
@router.post("/{floor_plan_id}/image", response_model=FloorPlanRead)
async def upload_floor_plan_image(
    floor_plan_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Upload de imagem da planta:

    - salva arquivo em media/floor_plans/
    - atualiza image_url da FloorPlan para /media/floor_plans/...
    """
    db_obj = await crud_floor_plan.get(db, id=floor_plan_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Floor plan not found")

    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    # pasta base de mídia
    media_root = Path(settings.media_root)
    floor_dir = media_root / "floor_plans"
    floor_dir.mkdir(parents=True, exist_ok=True)

    original_name = file.filename or f"floor_{floor_plan_id}"
    ext = Path(original_name).suffix or ".png"
    filename = f"floor_{floor_plan_id}{ext}"

    dest_path = floor_dir / filename

    content = await file.read()
    dest_path.write_bytes(content)

    # caminho público que o frontend vai usar
    rel_path = f"floor_plans/{filename}"
    image_url = f"{settings.public_base_url.rstrip('/')}/media/{rel_path}"

    updated = await crud_floor_plan.update(
        db,
        db_obj,
        {"image_url": image_url},
    )
    return updated
