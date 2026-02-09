# app/db/session.py

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.base import Base


# ----------------------------------------------------------------------
# Engine assíncrono usando a URL já tratada em settings.database_url
# ----------------------------------------------------------------------
engine_kwargs = {
    "future": True,
    "echo": False,
}

# Em ambientes de teste/CI evitamos pool para não reutilizar conexões
# asyncpg entre event loops diferentes (erro: "attached to a different loop"
# / "another operation is in progress").
if os.getenv("SV_DB_NULL_POOL", "").lower() in {"1", "true", "yes"} or os.getenv("GITHUB_ACTIONS") == "true":
    engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(
    settings.database_url,
    **engine_kwargs,
)

# ----------------------------------------------------------------------
# Factory de sessão assíncrona
# ----------------------------------------------------------------------
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ----------------------------------------------------------------------
# Inicialização do banco (chamada no startup)
# ----------------------------------------------------------------------
async def init_db() -> None:
    """
    Cria as tabelas no banco com base no Base.metadata.

    Em produção, o ideal é usar Alembic para migrations.
    Para desenvolvimento/local, isso aqui resolve.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ----------------------------------------------------------------------
# Dependency padrão para FastAPI (usada em get_db_session)
# ----------------------------------------------------------------------
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency para injetar AsyncSession em endpoints (via Depends).
    Garante abertura e fechamento correto da sessão.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
