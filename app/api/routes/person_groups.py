# app/api/routes/person_groups.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_db_session
from app.crud.person_group import person_group as crud_person_group
from app.models.person import Person  # 👈 novo
from app.schemas.person_group import (
    PersonGroupCreate,
    PersonGroupRead,
    PersonGroupUpdate,
    PersonGroupWithMembers,
    PersonGroupMembersUpdate,
)
from app.schemas.person import PersonRead

router = APIRouter()


@router.get("/", response_model=List[PersonGroupRead])
async def list_person_groups(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db_session),
):
    return await crud_person_group.get_multi(db, skip=skip, limit=limit)


@router.post("/", response_model=PersonGroupRead, status_code=status.HTTP_201_CREATED)
async def create_person_group(
    group_in: PersonGroupCreate,
    db: AsyncSession = Depends(get_db_session),
):
    return await crud_person_group.create(db, group_in)


@router.get("/{group_id}", response_model=PersonGroupRead)
async def get_person_group(
    group_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_person_group.get(db, id=group_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Person group not found")
    return db_obj


@router.put("/{group_id}", response_model=PersonGroupRead)
async def update_person_group(
    group_id: int,
    group_in: PersonGroupUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    db_obj = await crud_person_group.get(db, id=group_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Person group not found")
    return await crud_person_group.update(db, db_obj, group_in)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person_group(
    group_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    deleted = await crud_person_group.remove(db, id=group_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Person group not found")
    return None


@router.get(
    "/{group_id}/people",
    response_model=List[PersonRead],
)
async def list_person_group_members(
    group_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    group = await crud_person_group.get(db, id=group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Person group not found")

    # Garantir que a relationship people esteja carregada (normalmente lazy)
    await db.refresh(group)  # opcional, dependendo da config de relationship

    return group.people


@router.put(
    "/{group_id}/people",
    response_model=PersonGroupWithMembers,
)
async def set_person_group_members(
    group_id: int,
    members_in: PersonGroupMembersUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    group = await crud_person_group.get(db, id=group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Person group not found")

    # Busca todas as pessoas cujo ID está em people_ids
    if members_in.people_ids:
        stmt = select(Person).where(Person.id.in_(members_in.people_ids))
        result = await db.execute(stmt)
        people = list(result.scalars().all())
    else:
        people = []

    # Atualiza membership (estratégia simples: substitui tudo)
    group.people = people
    await db.commit()
    await db.refresh(group)

    return group

@router.get(
    "/{group_id}/with-members",
    response_model=PersonGroupWithMembers,
)
async def get_person_group_with_members(
    group_id: int,
    db: AsyncSession = Depends(get_db_session),
):
    group = await crud_person_group.get(db, id=group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Person group not found")

    await db.refresh(group)
    return group