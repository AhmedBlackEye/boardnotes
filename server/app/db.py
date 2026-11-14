"""Async Postgres access. One pool per app; rows come back as dicts."""

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

Conn = AsyncConnection[DictRow]
Pool = AsyncConnectionPool[Conn]


def create_pool(database_url: str, *, min_size: int = 1, max_size: int = 10) -> Pool:
    """Create a closed pool; the app lifespan opens it with `await pool.open()`."""
    return AsyncConnectionPool(
        database_url,
        connection_class=AsyncConnection[DictRow],
        kwargs={"row_factory": dict_row},
        min_size=min_size,
        max_size=max_size,
        open=False,
    )


# SQL in this codebase is always a constant string with %(name)s parameters; values are never formatted in.
async def fetch_one(conn: Conn, sql: str, params: dict[str, Any] | None = None) -> DictRow | None:
    cur = await conn.execute(sql.encode(), params)
    return await cur.fetchone()


async def fetch_all(conn: Conn, sql: str, params: dict[str, Any] | None = None) -> list[DictRow]:
    cur = await conn.execute(sql.encode(), params)
    return await cur.fetchall()


async def execute(conn: Conn, sql: str, params: dict[str, Any] | None = None) -> int:
    cur = await conn.execute(sql.encode(), params)
    return cur.rowcount
