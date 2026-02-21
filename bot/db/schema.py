from __future__ import annotations

import logging

from bot.db.database import get_db

log = logging.getLogger(__name__)


async def ensure_schema() -> None:
    db = get_db()

    # --- users ---
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """
    )

    cols = await _table_columns("users")
    if "id" in cols and "user_id" not in cols:
        log.warning("Migrating users.id -> users.user_id")
        await db.execute("ALTER TABLE users RENAME TO users_old;")
        await db.execute(
            """
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY,
                created_at TEXT DEFAULT (datetime('now'))
            );
            """
        )
        await db.execute(
            """
            INSERT OR IGNORE INTO users(user_id, created_at)
            SELECT id, COALESCE(created_at, datetime('now')) FROM users_old;
            """
        )
        await db.execute("DROP TABLE users_old;")

    # --- events ---
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            organizer_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            event_format TEXT DEFAULT 'single',

            start_date TEXT,
            end_date TEXT,
            start_time TEXT,
            end_time TEXT,

            location TEXT,
            price_text TEXT,
            ticket_link TEXT,
            phone TEXT,

            photo_ids TEXT DEFAULT '[]',

            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),

            approved_by INTEGER,
            rejected_by INTEGER,

            FOREIGN KEY (organizer_id) REFERENCES users(user_id)
        );
        """
    )

    # миграции “на лету” (самое частое у тебя в логах)
    await _add_column_if_missing("events", "category", "TEXT")
    await _add_column_if_missing("events", "price_text", "TEXT")
    await _add_column_if_missing("events", "photo_ids", "TEXT DEFAULT '[]'")
    await _add_column_if_missing("events", "status", "TEXT DEFAULT 'pending'")
    await _add_column_if_missing("events", "approved_by", "INTEGER")
    await _add_column_if_missing("events", "rejected_by", "INTEGER")
    await _add_column_if_missing("events", "event_format", "TEXT DEFAULT 'single'")
    await _add_column_if_missing("events", "start_date", "TEXT")
    await _add_column_if_missing("events", "end_date", "TEXT")
    await _add_column_if_missing("events", "start_time", "TEXT")
    await _add_column_if_missing("events", "end_time", "TEXT")
    await _add_column_if_missing("events", "description", "TEXT DEFAULT ''")

    cols = await _table_columns("events")
    if "category_text" in cols and "category" in cols:
        await db.execute(
            "UPDATE events SET category = COALESCE(NULLIF(category,''), category_text) WHERE category_text IS NOT NULL;"
        )

    await db.commit()


async def _table_columns(table: str) -> set[str]:
    db = get_db()
    cur = await db.execute(f"PRAGMA table_info({table});")
    rows = await cur.fetchall()
    return {r["name"] for r in rows}


async def _add_column_if_missing(table: str, col: str, decl: str) -> None:
    db = get_db()
    cols = await _table_columns(table)
    if col in cols:
        return
    await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl};")