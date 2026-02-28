# bot/db/schema.py
from __future__ import annotations

from bot.db.database import get_db

# ВАЖНО:
# НЕ добавляем сюда индексы, которые ссылаются на новые колонки,
# потому что на старой БД этих колонок может не быть и бот упадёт на старте.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE NOT NULL,
    role TEXT NOT NULL DEFAULT 'resident',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organizer_id INTEGER NOT NULL,

    category TEXT NOT NULL DEFAULT '',
    category_text TEXT NOT NULL DEFAULT '',

    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',

    event_format TEXT NOT NULL DEFAULT '',

    event_date TEXT,
    event_time TEXT,

    start_date TEXT,
    end_date TEXT,
    open_time TEXT,
    close_time TEXT,

    sessions_start_date TEXT,
    sessions_end_date TEXT,
    sessions_times TEXT,

    location TEXT NOT NULL DEFAULT '',
    price_text TEXT NOT NULL DEFAULT '',
    ticket_link TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',

    status TEXT NOT NULL DEFAULT 'pending',

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    -- продвижение/платные опции
    promoted_kind TEXT NOT NULL DEFAULT '',
    promoted_until TEXT,
    highlighted INTEGER NOT NULL DEFAULT 0,
    bumped_at TEXT
);

CREATE TABLE IF NOT EXISTS event_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    file_id TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS promo_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organizer_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,

    service TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'RUB',

    status TEXT NOT NULL DEFAULT 'created',
    provider TEXT NOT NULL DEFAULT 'yookassa',

    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    paid_at TEXT,

    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
);
"""


async def _table_columns(table: str) -> set[str]:
    db = get_db()
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return {r["name"] for r in rows}


async def _add_column_if_missing(table: str, column: str, ddl: str) -> None:
    cols = await _table_columns(table)
    if column in cols:
        return
    db = get_db()
    await db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    await db.commit()


async def _create_indexes_safely() -> None:
    """
    Создаём индексы ПОСЛЕ миграций.
    Если колонок нет — индекс не создаём.
    """
    db = get_db()

    # базовые индексы (безопасны)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_events_status ON events(status)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_events_dates ON events(start_date, event_date)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_events_org ON events(organizer_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_event_photos_event ON event_photos(event_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_promo_orders_event ON promo_orders(event_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_promo_orders_org ON promo_orders(organizer_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_promo_orders_status ON promo_orders(status)")

    # индекс по продвижению — только если колонки реально есть
    ecols = await _table_columns("events")
    if {"promoted_kind", "promoted_until", "highlighted"}.issubset(ecols):
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_promoted "
            "ON events(promoted_kind, promoted_until, highlighted)"
        )

    await db.commit()


async def ensure_schema() -> None:
    db = get_db()

    # 1) создаём таблицы
    await db.executescript(SCHEMA_SQL)
    await db.commit()

    # 2) миграции (подтягиваем колонки на старых БД)
    # users
    await _add_column_if_missing("users", "user_id", "user_id INTEGER UNIQUE NOT NULL DEFAULT 0")
    await _add_column_if_missing("users", "role", "role TEXT NOT NULL DEFAULT 'resident'")

    # events
    await _add_column_if_missing("events", "category_text", "category_text TEXT NOT NULL DEFAULT ''")
    await _add_column_if_missing("events", "promoted_kind", "promoted_kind TEXT NOT NULL DEFAULT ''")
    await _add_column_if_missing("events", "promoted_until", "promoted_until TEXT")
    await _add_column_if_missing("events", "highlighted", "highlighted INTEGER NOT NULL DEFAULT 0")
    await _add_column_if_missing("events", "bumped_at", "bumped_at TEXT")

    # promo_orders
    await _add_column_if_missing("promo_orders", "payload_json", "payload_json TEXT NOT NULL DEFAULT '{}'")
    await _add_column_if_missing("promo_orders", "provider", "provider TEXT NOT NULL DEFAULT 'yookassa'")
    await _add_column_if_missing("promo_orders", "currency", "currency TEXT NOT NULL DEFAULT 'RUB'")
    await _add_column_if_missing("promo_orders", "amount", "amount INTEGER NOT NULL DEFAULT 0")

    # 3) индексы — только после миграций
    await _create_indexes_safely()