# securityvision-position/alembic/env.py
import os
import sys
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ---------------------------------------------------------
# Garantir que o diretório raiz do projeto entre no sys.path
# ---------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # .../securityvision-position
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app.db.base_class import Base
from app.core.config import settings  # 👈 NOVO

# ---------------------------------------------------------
# Config Alembic
# ---------------------------------------------------------
config = context.config

# 👇 FORÇA o Alembic a usar a MESMA URL do app
config.set_main_option("sqlalchemy.url", settings.database_url)

# se tiver logging configurado no alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# metadata que o Alembic vai usar para autogenerate, etc.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Modo offline: gera o SQL sem conectar de fato no banco.
    """
    url = settings.database_url  # 👈 usa Settings também aqui
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """
    Função auxiliar para rodar as migrações usando uma conexão síncrona
    criada a partir do engine assíncrono.
    """
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """
    Modo online: usa async engine (postgresql+asyncpg).
    """
    # aqui o sqlalchemy.url já foi sobrescrito acima com settings.database_url
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        # run_sync converte a connection async em uma connection sync
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
