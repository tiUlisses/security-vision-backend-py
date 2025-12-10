# app/api/deps.py
from typing import AsyncGenerator
from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import ALGORITHM, SECRET_KEY  # 👈 vamos expor já
from app.crud.user import user as crud_user
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.schemas.user import TokenPayload


from app.db.session import AsyncSessionLocal

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    db: AsyncSession = Depends(get_db_session),
    token: str = Depends(oauth2_scheme),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não foi possível validar as credenciais",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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