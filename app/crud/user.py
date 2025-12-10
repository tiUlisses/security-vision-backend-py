# app/crud/user.py
from typing import Any, Dict, Optional, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate


class CRUDUser(CRUDBase[User, UserCreate, UserUpdate]):
    async def get_by_email(
        self,
        db: AsyncSession,
        *,
        email: str,
    ) -> Optional[User]:
        stmt = select(User).where(User.email == email)
        result = await db.execute(stmt)
        return result.scalars().first()

    async def create_with_hashed_password(
        self,
        db: AsyncSession,
        *,
        obj_in: UserCreate,
        hashed_password: str,
    ) -> User:
        """
        Cria o usuário já com a senha hash, COMMITA a transação e
        faz refresh para retornar o objeto sincronizado com o banco.
        """
        db_obj = User(
            email=obj_in.email,
            full_name=obj_in.full_name,
            role=obj_in.role,
            hashed_password=hashed_password,
            is_active=obj_in.is_active,
            is_superuser=obj_in.is_superuser,
        )
        db.add(db_obj)
        # 👇 ESSA LINHA É A MAIS IMPORTANTE
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update(
        self,
        db: AsyncSession,
        *,
        db_obj: User,
        obj_in: Union[UserUpdate, Dict[str, Any]],
    ) -> User:
        # reaproveita a lógica padrão de update do CRUDBase
        return await super().update(db, db_obj=db_obj, obj_in=obj_in)


user = CRUDUser(User)