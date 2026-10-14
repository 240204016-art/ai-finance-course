"""Подключение к SQLite и инициализация схемы."""
from __future__ import annotations

from pathlib import Path

import aiosqlite

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


async def connect(db_path: Path | str) -> aiosqlite.Connection:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    await conn.commit()
    return conn
