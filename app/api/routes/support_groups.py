from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_admin_user
from app.schemas.support_group import (
    SupportGroupCreate,
    SupportGroupUpdate,
    SupportGroupRead,
)
from app.crud.support_group import support_group as crud_group

router = APIRouter(prefix="/support-groups", tags=["support-groups"])


@router.get("/", response_model=list[SupportGroupRead])
async def list_groups(
    db: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_admin_user),
):
    return await crud_group.list_all(db)


@router.post("/", response_model=SupportGroupRead)
async def create_group(
    group_in: SupportGroupCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_admin_user),
):
    # 🔹 evita violar unique e devolver 500
    existing = await crud_group.get_by_name(db, name=group_in.name)
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Já existe um grupo com esse nome.",
        )

    return await crud_group.create_with_members(db, obj_in=group_in)


@router.put("/{group_id}", response_model=SupportGroupRead)
async def update_group(
    group_id: int,
    group_in: SupportGroupUpdate,
    db: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_admin_user),
):
    group = await crud_group.get(db, id=group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo não encontrado")

    # se quiser, pode validar nome duplicado aqui também:
    # if group_in.name and group_in.name != group.name:
    #     existing = await crud_group.get_by_name(db, name=group_in.name)
    #     if existing:
    #         raise HTTPException(
    #             status_code=400,
    #             detail="Já existe um grupo com esse nome.",
    #         )

    return await crud_group.update_with_members(db, db_obj=group, obj_in=group_in)
