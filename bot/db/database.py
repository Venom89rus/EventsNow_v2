from __future__ import annotations

from pathlib import Path
from typing import Optional

import aiosqlite

_db: Optional[aiosqlite.Connection] = None


def _dsn_to_path(dsn: str) -> str:
    dsn = (dsn or "").strip()
    if not dsn:
        return str(Path("data") / "eventsnow.db")

    if dsn.startswith("sqlite:///"):
        return dsn[len("sqlite:///") :]
    if dsn.startswith("sqlite://"):
        return dsn[len("sqlite://") :]

    return dsn


async def init_db(dsn: str) -> None:
    global _db
    if _db is not None:
        return

    db_path = _dsn_to_path(dsn).strip().strip('"').strip("'")
    p = Path(db_path)

    # если дали папку — кладём файл внутрь
    if str(db_path).endswith(("/", "\\")) or (p.exists() and p.is_dir()):
        p = p / "eventsnow.db"

    # создаём директории
    if p.parent and str(p.parent) not in ("", "."):
        p.parent.mkdir(parents=True, exist_ok=True)

    _db = await aiosqlite.connect(str(p))
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA foreign_keys = ON;")
    await _db.execute("PRAGMA journal_mode = WAL;")
    await _db.commit()


def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("DB is not initialized. Call init_db() first.")
    return _db


async def close_db() -> None:
    global _db
    if _db is None:
        return
    await _db.close()
    _db = None