import pytest_asyncio
from sqlalchemy import inspect, text

from app.db.session import engine


@pytest_asyncio.fixture(autouse=True)
async def clean_database() -> None:
    """Isola os testes limpando tabelas entre execuções.

    Evita colisões de UNIQUE (ex.: mac_address) quando os cenários reutilizam
    os mesmos valores em múltiplos testes.
    """

    def _truncate_all(sync_conn) -> None:
        inspector = inspect(sync_conn)
        table_names = [t for t in inspector.get_table_names(schema="public") if t != "alembic_version"]
        if not table_names:
            return

        tables_sql = ", ".join(f'"public"."{name}"' for name in table_names)
        sync_conn.execute(text(f"TRUNCATE TABLE {tables_sql} RESTART IDENTITY CASCADE"))

    async with engine.begin() as conn:
        await conn.run_sync(_truncate_all)

    yield

    async with engine.begin() as conn:
        await conn.run_sync(_truncate_all)
