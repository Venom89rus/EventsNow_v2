from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from bot.db.database import get_db


@dataclass
class Event:
    id: int
    organizer_id: int
    category: str
    title: str
    description: str
    event_format: str
    start_date: str
    end_date: str
    start_time: str
    end_time: str
    location: str
    price_text: str
    ticket_link: str
    phone: str
    photo_ids: list[str]
    status: str


def _row_to_event(row: Any) -> Event:
    # Row в sqlite/aiosqlite: нет .get(), только ["col"] и keys()
    def col(name: str, default: Any = "") -> Any:
        try:
            if hasattr(row, "keys") and name in row.keys():
                v = row[name]
                return default if v is None else v
        except Exception:
            pass
        return default

    raw = col("photo_ids", "[]")
    try:
        photos = json.loads(raw) if raw else []
        if not isinstance(photos, list):
            photos = []
    except Exception:
        photos = []

    return Event(
        id=int(col("id", 0)),
        organizer_id=int(col("organizer_id", 0)),
        category=str(col("category", "")),
        title=str(col("title", "")),
        description=str(col("description", "")),
        event_format=str(col("event_format", "single")),
        start_date=str(col("start_date", "")),
        end_date=str(col("end_date", "")),
        start_time=str(col("start_time", "")),
        end_time=str(col("end_time", "")),
        location=str(col("location", "")),
        price_text=str(col("price_text", "")),
        ticket_link=str(col("ticket_link", "")),
        phone=str(col("phone", "")),
        photo_ids=photos,
        status=str(col("status", "pending")),
    )


async def ensure_user(user_id: int) -> None:
    db = get_db()
    await db.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?);", (int(user_id),))
    await db.commit()


async def create_event(
    *,
    organizer_id: int,
    category: str,
    title: str,
    description: str,
    event_format: str,
    start_date: str,
    end_date: str,
    start_time: str,
    end_time: str,
    location: str,
    price_text: str,
    ticket_link: str,
    phone: str,
    photo_ids: Sequence[str] | None = None,
    status: str = "pending",
) -> int:
    db = get_db()
    photo_json = json.dumps(list(photo_ids or []), ensure_ascii=False)

    cur = await db.execute(
        """
        INSERT INTO events(
            organizer_id, category, title, description, event_format,
            start_date, end_date, start_time, end_time,
            location, price_text, ticket_link, phone,
            photo_ids, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            int(organizer_id),
            category,
            title,
            description,
            event_format,
            start_date,
            end_date,
            start_time,
            end_time,
            location,
            price_text,
            ticket_link,
            phone,
            photo_json,
            status,
        ),
    )
    await db.commit()
    return int(cur.lastrowid)


async def get_event(event_id: int) -> Optional[Event]:
    db = get_db()
    cur = await db.execute("SELECT * FROM events WHERE id = ?;", (int(event_id),))
    row = await cur.fetchone()
    return _row_to_event(row) if row else None


async def get_pending_events(limit: int = 30) -> list[Event]:
    db = get_db()
    cur = await db.execute(
        "SELECT * FROM events WHERE status='pending' ORDER BY id ASC LIMIT ?;",
        (int(limit),),
    )
    rows = await cur.fetchall()
    return [_row_to_event(r) for r in rows]


async def approve_event(event_id: int, admin_id: int) -> bool:
    db = get_db()
    cur = await db.execute(
        "UPDATE events SET status='approved', approved_by=? WHERE id=? AND status='pending';",
        (int(admin_id), int(event_id)),
    )
    await db.commit()
    return cur.rowcount > 0


async def reject_event(event_id: int, admin_id: int) -> bool:
    db = get_db()
    cur = await db.execute(
        "UPDATE events SET status='rejected', rejected_by=? WHERE id=? AND status='pending';",
        (int(admin_id), int(event_id)),
    )
    await db.commit()
    return cur.rowcount > 0


class Repo:
    async def ensure_user(self, user_id: int) -> None:
        return await ensure_user(user_id)

    async def create_event(self, **kwargs: Any) -> int:
        return await create_event(**kwargs)

    async def get_event(self, event_id: int) -> Optional[Event]:
        return await get_event(event_id)

    async def get_pending_events(self, limit: int = 30) -> list[Event]:
        return await get_pending_events(limit=limit)

    async def approve_event(self, event_id: int, admin_id: int) -> bool:
        return await approve_event(event_id, admin_id)

    async def reject_event(self, event_id: int, admin_id: int) -> bool:
        return await reject_event(event_id, admin_id)


repo = Repo()