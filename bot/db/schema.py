from __future__ import annotations

from bot.db.database import get_db

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    role TEXT NOT NULL DEFAULT 'resident',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organizer_id INTEGER NOT NULL,

    category TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    event_format TEXT NOT NULL, -- single | period | sessions

    -- single
    event_date TEXT,
    event_time TEXT,

    -- period
    start_date TEXT,
    end_date TEXT,
    open_time TEXT,
    close_time TEXT,

    -- sessions
    sessions_start_date TEXT,
    sessions_end_date TEXT,
    sessions_times TEXT, -- "10:00, 12:30, 15:00"

    location TEXT NOT NULL,
    price_text TEXT NOT NULL,
    ticket_link TEXT NOT NULL,
    phone TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'pending', -- pending | approved | rejected
    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (organizer_id) REFERENCES users(user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS event_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    file_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

-- promo orders (Юкасса / доп. услуги: топ, рассылка и т.п.)
CREATE TABLE IF NOT EXISTS promo_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organizer_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    service TEXT NOT NULL,            -- 'top' | 'broadcast' | ...
    amount_rub INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',  -- created | paid | canceled
    payload_json TEXT NOT NULL DEFAULT '{}', -- любые доп. данные (json)
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    paid_at TEXT,

    FOREIGN KEY (organizer_id) REFERENCES users(user_id) ON DELETE RESTRICT,
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_events_category ON events(category);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_event_photos_event_id ON event_photos(event_id);

CREATE INDEX IF NOT EXISTS idx_promo_orders_status ON promo_orders(status);
CREATE INDEX IF NOT EXISTS idx_promo_orders_org ON promo_orders(organizer_id);
CREATE INDEX IF NOT EXISTS idx_promo_orders_event ON promo_orders(event_id);
"""


async def _add_column_if_missing(table: str, column: str, ddl: str) -> None:
    """
    Добавляет колонку через ALTER TABLE, если её ещё нет.
    ddl — это кусок "column_name TYPE ...".
    """
    db = get_db()
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    cols = {r[1] for r in rows}  # r[1] = column name
    if column in cols:
        return
    await db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    await db.commit()


async def ensure_schema() -> None:
    db = get_db()
    await db.executescript(SCHEMA_SQL)
    await db.commit()

    # ---- МИГРАЦИИ (если БД была создана раньше) ----
    # promo_orders.payload_json мог отсутствовать
    await _add_column_if_missing(
        "promo_orders",
        "payload_json",
        "payload_json TEXT NOT NULL DEFAULT '{}'",
    )

    # promo_orders.service мог отсутствовать (в старых версиях)
    # В SQLite нельзя просто добавить NOT NULL без DEFAULT — поэтому даём DEFAULT ''.
    await _add_column_if_missing(
        "promo_orders",
        "service",
        "service TEXT NOT NULL DEFAULT ''",
    )

    # promo_orders.amount_rub мог отсутствовать
    await _add_column_if_missing(
        "promo_orders",
        "amount_rub",
        "amount_rub INTEGER NOT NULL DEFAULT 0",
    )

    # promo_orders.paid_at мог отсутствовать
    await _add_column_if_missing(
        "promo_orders",
        "paid_at",
        "paid_at TEXT",
    )

    # ---- PROMO поля в events ----
    await _add_column_if_missing(
        "events",
        "promoted_kind",
        "promoted_kind TEXT",  # например 'top' / 'broadcast'
    )
    await _add_column_if_missing(
        "events",
        "promoted_at",
        "promoted_at TEXT",
    )
    await _add_column_if_missing(
        "events",
        "promoted_until",
        "promoted_until TEXT",
    )