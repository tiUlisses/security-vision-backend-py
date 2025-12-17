# app/api/routes/auth.py
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session
from app.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_password_hash,
    verify_password,
)
from app.crud.user import user as crud_user
from app.models.user import User
from app.schemas.user import (
    LoginRequest,
    Token,
    UserCreate,
    UserRead,
)

router = APIRouter()


@router.post("/login", response_model=Token)
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db_session),
) -> Token:
    db_user = await crud_user.get_by_email(db, email=data.email)
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E-mail ou senha inválidos",
        )

    if not verify_password(data.password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E-mail ou senha inválidos",
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token_str = create_access_token(
        subject=db_user.id,
        role=db_user.role,
        expires_delta=access_token_expires,
    )

    return Token(access_token=token_str, token_type="bearer")


@router.post("/signup", response_model=UserRead)
async def signup(
    data: UserCreate,
    db: AsyncSession = Depends(get_db_session),
) -> UserRead:
    # 🔐 Signup fica disponível apenas para bootstrap do primeiro admin
    # (quando ainda não existe nenhum admin/superuser no banco).
    has_admin = await crud_user.has_admin(db)
    if has_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signup desabilitado. Apenas admins podem criar usuários.",
        )

    existing = await crud_user.get_by_email(db, email=data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Já existe um usuário com este e-mail",
        )

    # Força criação de admin/superuser no bootstrap
    if hasattr(data, "model_copy"):
        data = data.model_copy(update={"role": "ADMIN", "is_superuser": True})
    else:
        data = data.copy(update={"role": "ADMIN", "is_superuser": True})

    hashed_pwd = get_password_hash(data.password)
    user_obj = await crud_user.create_with_hashed_password(
        db,
        obj_in=data,
        hashed_password=hashed_pwd,
    )
    return user_obj


@router.get("/me", response_model=UserRead)
async def read_me(
    current_user: User = Depends(get_current_active_user),
) -> UserRead:
    return current_user
