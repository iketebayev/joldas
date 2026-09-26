import os
from pathlib import Path

import asyncpg

_pool: asyncpg.Pool | None = None


async def init_pool(apply_schema: bool = True) -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        host=os.getenv("POSTGRES_HOST", "db"),
        user=os.getenv("POSTGRES_USER", "app"),
        password=os.environ["POSTGRES_PASSWORD"],
        database=os.getenv("POSTGRES_DB", "app"),
        min_size=1,
        max_size=10,
    )
    if not apply_schema:  # воркер: схему применяет app, иначе гонка DDL при старте
        return
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    async with _pool.acquire() as c:
        await c.execute(schema)


async def close_pool() -> None:
    if _pool:
        await _pool.close()


def pool() -> asyncpg.Pool:
    assert _pool is not None, "init_pool() не вызван"
    return _pool
