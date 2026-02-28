# bot/db/database.py
from __future__ import annotations

import os
import sqlite3
import logging
from pathlib import Path
from urllib.parse import urlparse, unquote

import aiosqlite

_db: aiosqlite.Connection | None = None


def _default_db_path() -> str:
    # Храним БД рядом с проектом: bot/db/events.db
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../bot
    return os.path.join(base_dir, "db", "events.db")


def _normalize_db_path(db_url_or_path: str | None) -> str:
    """
    Поддержка:
    - "events.db"
    - "./data/events.db"
    - "sqlite:events.db"
    - "sqlite:./data/events.db"
    - "sqlite:///C:/path/to/events.db"
    - "sqlite:///./data/events.db"
    - "sqlite:"  -> fallback to default

    ВАЖНО: если в окружении задан SQLITE_PATH — он имеет приоритет.
    """
    # 1) Самый надежный источник — env SQLITE_PATH
    env_path = (os.getenv("SQLITE_PATH") or "").strip()
    if env_path:
        return env_path

    s = (db_url_or_path or "").strip()
    if not s:
        return _default_db_path()

    # sqlite URL
    if s.startswith("sqlite:"):
        parsed = urlparse(s)

        # Примеры:
        # sqlite:events.db  -> scheme sqlite, path "events.db"
        # sqlite:./x.db     -> path "./x.db"
        # sqlite:///C:/x.db -> path "/C:/x.db"
        path = parsed.path or ""
        path = unquote(path)

        # sqlite:///C:/... -> убираем первый "/" чтобы Windows понял диск
        if path.startswith("/") and len(path) >= 3 and path[2] == ":":
            path = path[1:]

        # Если это просто "sqlite:" без пути — берём дефолт
        if not path:
            return _default_db_path()

        return path

    # иначе это обычный путь
    return s


def _resolve_path(p: str) -> str:
    """
    Приводим путь к абсолютному, разворачиваем ~ и относительные пути.
    """
    pp = Path(p).expanduser()
    # Если путь относительный — делаем относительно корня проекта (папка выше /bot)
    if not pp.is_absolute():
        project_root = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # .../bot
        # project_root сейчас указывает на .../bot, нам нужен корень проекта: .../
        project_root = project_root.parent
        pp = (project_root / pp)
    return str(pp.resolve())


async def init_db(db_url_or_path: str | None = None) -> None:
    """
    Инициализация единственного подключения к SQLite на процесс.
    Важно: НЕ создаём новые подключения в хэндлерах.

    Источник пути:
    1) SQLITE_PATH из .env (если задан)
    2) аргумент db_url_or_path
    3) дефолт bot/db/events.db
    """
    global _db
    if _db is not None:
        return

    raw_path = _normalize_db_path(db_url_or_path)
    db_path = _resolve_path(raw_path)

    folder = os.path.dirname(db_path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    conn = await aiosqlite.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Нормальные pragma
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.execute("PRAGMA synchronous = NORMAL")

    _db = conn

    # ЛОГИРУЕМ РЕАЛЬНЫЙ ФАЙЛ, С КОТОРЫМ РАБОТАЕТ БОТ
    logging.info("✅ SQLite DB ready: %s", db_path)


def get_db() -> aiosqlite.Connection:
    """
    НЕ async. Нельзя делать: await get_db()
    """
    if _db is None:
        raise RuntimeError("DB is not initialized. Call init_db() on startup.")
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None