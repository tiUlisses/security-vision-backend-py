# app/db/session.py

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base  # 🔴 ajuste o import se o seu Base estiver em outro módulo


# ----------------------------------------------------------------------
# Engine assíncrono usando a URL já tratada em settings.database_url
# ----------------------------------------------------------------------
engine = create_async_engine(
    settings.database_url,
    future=True,
    echo=False,  # coloque True se quiser ver o SQL no log
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
