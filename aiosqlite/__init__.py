"""
Mini-implementação embutida de aiosqlite para ambientes offline.

Esta versão cobre apenas o conjunto de recursos necessários para o SQLAlchemy
em modo assíncrono usado nos testes automatizados (create_all, CRUD básico).
Não é otimizada para produção.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Iterable, Optional

# Exceções esperadas pelo dialeto do SQLAlchemy
DatabaseError = sqlite3.DatabaseError
IntegrityError = sqlite3.IntegrityError
ProgrammingError = sqlite3.ProgrammingError
OperationalError = sqlite3.OperationalError
Error = sqlite3.Error
Warning = sqlite3.Warning
Binary = sqlite3.Binary
Row = sqlite3.Row
Version = sqlite3.version
sqlite_version = sqlite3.sqlite_version
sqlite_version_info = sqlite3.sqlite_version_info
NotSupportedError = sqlite3.NotSupportedError
InterfaceError = sqlite3.InterfaceError
DataError = sqlite3.DataError

def _run_sync(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, lambda: func(*args, **kwargs))


class Cursor:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    async def fetchone(self):
        return await _run_sync(self._cursor.fetchone)

    async def fetchmany(self, size: int | None = None):
        return await _run_sync(self._cursor.fetchmany, size) if size else await _run_sync(self._cursor.fetchmany)

    async def fetchall(self):
        return await _run_sync(self._cursor.fetchall)

    async def close(self):
        return await _run_sync(self._cursor.close)

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def __getattr__(self, item: str) -> Any:
        # delega atributos simples (ex.: description)
        return getattr(self._cursor, item)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class Connection:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    async def execute(self, sql: str, parameters: Iterable | None = None):
        cursor = await _run_sync(self._conn.execute, sql, parameters or ())
        return Cursor(cursor)

    async def executemany(self, sql: str, seq_of_parameters: Iterable[Iterable]):
        cursor = await _run_sync(self._conn.executemany, sql, seq_of_parameters)
        return Cursor(cursor)

    async def executescript(self, script: str):
        cursor = await _run_sync(self._conn.executescript, script)
        return Cursor(cursor)

    async def cursor(self):
        cur = await _run_sync(self._conn.cursor)
        return Cursor(cur)

    async def commit(self):
        return await _run_sync(self._conn.commit)

    async def rollback(self):
        return await _run_sync(self._conn.rollback)

    async def close(self):
        return await _run_sync(self._conn.close)

    def __getattr__(self, item: str) -> Any:
        # permite acesso a atributos como row_factory
        return getattr(self._conn, item)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class _ConnectWrapper:
    def __init__(self, coro):
        self._coro = coro
        # usado pelo dialeto do SQLAlchemy
        self.daemon = True

    def __await__(self):
        return self._coro.__await__()


def connect(database: str, **kwargs):
    # Mantém check_same_thread=False para permitir acesso em diferentes tasks
    async def _coro():
        conn = sqlite3.connect(database, **kwargs)
        return Connection(conn)

    return _ConnectWrapper(_coro())
