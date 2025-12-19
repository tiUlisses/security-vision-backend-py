# app/api/deps.py
from collections.abc import AsyncGenerator  # ✅ esse basta

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import ALGORITHM, SECRET_KEY, decode_access_token
from app.crud.user import user as crud_user
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.schemas.user import TokenPayload

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False,  # permitimos fluxo opcional em modo dev/teste
)


def _dev_superuser() -> User:
    """
    Usuário fictício usado apenas quando ALLOW_ANONYMOUS_DEV_MODE=True.
    Evita 403 em ambientes de teste sem token configurado.
    """
    return User(
        id=0,
        email="dev@local",
        full_name="Dev Admin",
        hashed_password="",
        role="SUPERADMIN",
        is_active=True,
        is_superuser=True,
    )


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    db: AsyncSession = Depends(get_db_session),
    token: str | None = Depends(oauth2_scheme),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não foi possível validar as credenciais",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        if settings.ALLOW_ANONYMOUS_DEV_MODE:
            return _dev_superuser()
        raise credentials_exception
    try:
        payload = decode_access_token(token)
        sub = payload.get("sub")
        if sub is None:
            raise credentials_exception

        token_data = TokenPayload(
            sub=int(sub),
            exp=payload.get("exp"),
            role=payload.get("role") or "OPERATOR",
        )
    except (JWTError, ValueError):
        raise credentials_exception

    user_db = await crud_user.get(db, id=token_data.sub)
    if not user_db:
        raise credentials_exception

    return user_db


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Usuário inativo")
    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Garante que o usuário é admin/superuser antes de acessar a rota.
    Usa tanto o campo is_superuser quanto o campo role.
    """
    if not current_user.is_superuser and current_user.role not in ("ADMIN", "SUPERADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissão insuficiente para acessar este recurso.",
        )
    return current_user
