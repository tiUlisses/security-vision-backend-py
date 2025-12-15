# app/api/routes/users.py

from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.api.deps import get_current_admin_user, get_db_session
from app.core.security import get_password_hash
from app.crud.user import user as crud_user
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.models.support_group import SupportGroup
from app.models.user import User

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/", response_model=list[UserRead])
async def list_users(
    skip: int = 0,
    limit: int = 200,
    db: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_admin_user),
) -> list[UserRead]:
    return await crud_user.get_multi(db, skip=skip, limit=limit)


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_admin_user),
) -> UserRead:
    existing = await crud_user.get_by_email(db, email=data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Já existe um usuário com este e-mail",
        )

    hashed_pwd = get_password_hash(data.password)
    user_obj = await crud_user.create_with_hashed_password(
        db,
        obj_in=data,
        hashed_password=hashed_pwd,
    )
    return user_obj


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_admin_user),
) -> UserRead:
    user_db = await crud_user.get(db, id=user_id)
    if not user_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado",
        )

    user_db = await crud_user.update(db, db_obj=user_db, obj_in=data)
    return user_db

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_admin_user),
):
    user_db = await crud_user.get(db, id=user_id)
    if not user_db:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # ✅ remove o usuário de todos os grupos antes de deletar (evita FK / tabelas de associação)
    result = await db.execute(
        select(SupportGroup)
        .options(selectinload(SupportGroup.members))
        .where(SupportGroup.members.any(User.id == user_id))
    )
    affected_groups = result.scalars().all()

    for g in affected_groups:
        g.members = [m for m in (g.members or []) if m.id != user_id]

    await db.delete(user_db)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
