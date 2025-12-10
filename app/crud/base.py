# app/crud/base.py
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, Union

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base_class import Base  # ou onde estiver sua Base

ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    def __init__(self, model: Type[ModelType]):
        self.model = model

    async def get(self, db: AsyncSession, id: Any) -> Optional[ModelType]:
        stmt = select(self.model).where(self.model.id == id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self, db: AsyncSession, skip: int = 0, limit: int = 100
    ) -> List[ModelType]:
        stmt = select(self.model).offset(skip).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def create(
        self,
        db: AsyncSession,
        obj_in: Union[CreateSchemaType, Dict[str, Any]],
    ) -> ModelType:
        """
        Cria um objeto no banco.

        Aceita tanto:
        - um Pydantic (CreateSchemaType)
        - quanto um dict já pronto (caso do AlertEvent dentro do alert_engine).
        """
        if isinstance(obj_in, dict):
            obj_in_data = obj_in
        elif isinstance(obj_in, BaseModel):
            # Pydantic v2
            if hasattr(obj_in, "model_dump"):
                obj_in_data = obj_in.model_dump(exclude_unset=True)
            else:
                # compat Pydantic v1
                obj_in_data = obj_in.dict(exclude_unset=True)
        else:
            raise TypeError("obj_in must be a dict or a Pydantic BaseModel instance")

        db_obj = self.model(**obj_in_data)  # type: ignore[arg-type]
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update(
        self,
        db: AsyncSession,
        db_obj: ModelType,
        obj_in: Union[UpdateSchemaType, Dict[str, Any]],
    ) -> ModelType:
        if isinstance(obj_in, BaseModel):
            if hasattr(obj_in, "model_dump"):
                update_data = obj_in.model_dump(exclude_unset=True)
            else:
                update_data = obj_in.dict(exclude_unset=True)
        else:
            update_data = obj_in

        for field, value in update_data.items():
            setattr(db_obj, field, value)

        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def remove(self, db: AsyncSession, id: int) -> Optional[ModelType]:
        obj = await self.get(db, id)
        if obj is None:
            return None
        await db.delete(obj)
        await db.commit()
        return obj
