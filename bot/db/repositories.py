from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from bot.db.database import get_db


@dataclass
class Event:
    id: int
    organizer_id: int
    category: str
    title: str
    description: str
    event_format: str

    event_date: str | None
    event_time: str | None

    start_date: str | None
    end_date: str | None
    open_time: str | None
    close_time: str | None

    sessions_start_date: str | None
    sessions_end_date: str | None
    sessions_times: str | None

    location: str
    price_text: str
    ticket_link: str
    phone: str

    status: str
    created_at: str


def _col(row: Any, name: str, default: Any = None) -> Any:
    try:
        return row[name]
    except Exception:
        return default


def _row_to_event(row: Any) -> Event:
    return Event(
        id=int(_col(row, "id", 0)),
        organizer_id=int(_col(row, "organizer_id", 0)),
        category=str(_col(row, "category", "") or ""),
        title=str(_col(row, "title", "") or ""),
        description=str(_col(row, "description", "") or ""),
        event_format=str(_col(row, "event_format", "single") or "single"),

        event_date=_col(row, "event_date"),
        event_time=_col(row, "event_time"),

        start_date=_col(row, "start_date"),
        end_date=_col(row, "end_date"),
        open_time=_col(row, "open_time"),
        close_time=_col(row, "close_time"),

        sessions_start_date=_col(row, "sessions_start_date"),
        sessions_end_date=_col(row, "sessions_end_date"),
        sessions_times=_col(row, "sessions_times"),

        location=str(_col(row, "location", "") or ""),
        price_text=str(_col(row, "price_text", "") or ""),
        ticket_link=str(_col(row, "ticket_link", "") or ""),
        phone=str(_col(row, "phone", "") or ""),

        status=str(_col(row, "status", "pending") or "pending"),
        created_at=str(_col(row, "created_at", "") or ""),
    )


# =========================
# базовые функции (как у тебя логически было)
# =========================
async def ensure_user(user_id: int, role: str = "organizer") -> None:
    db = get_db()
    await db.execute(
        "INSERT OR IGNORE INTO users (user_id, role) VALUES (?, ?)",
        (user_id, role),
    )
    await db.commit()


async def create_event(
    *,
    organizer_id: int,
    category: str,
    title: str,
    description: str,
    event_format: str,  # single|period|sessions

    # single
    event_date: str | None = None,
    event_time: str | None = None,

    # period
    start_date: str | None = None,
    end_date: str | None = None,
    open_time: str | None = None,
    close_time: str | None = None,

    # sessions
    sessions_start_date: str | None = None,
    sessions_end_date: str | None = None,
    sessions_times: str | None = None,

    location: str = "",
    price_text: str = "",
    ticket_link: str = "",
    phone: str = "",
    status: str = "pending",
    photo_ids: list[str] | None = None,
) -> int:
    db = get_db()

    cur = await db.execute(
        """
        INSERT INTO events (
            organizer_id, category, title, description, event_format,
            event_date, event_time,
            start_date, end_date, open_time, close_time,
            sessions_start_date, sessions_end_date, sessions_times,
            location, price_text, ticket_link, phone,
            status
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?
        )
        """,
        (
            organizer_id, category, title, description, event_format,
            event_date, event_time,
            start_date, end_date, open_time, close_time,
            sessions_start_date, sessions_end_date, sessions_times,
            location, price_text, ticket_link, phone,
            status
        ),
    )
    await db.commit()

    event_id = int(cur.lastrowid)

    # фото
    if photo_ids:
        for idx, file_id in enumerate(photo_ids[:5], start=1):
            await db.execute(
                "INSERT INTO event_photos (event_id, file_id, position) VALUES (?, ?, ?)",
                (event_id, file_id, idx),
            )
        await db.commit()

    return event_id


async def get_event(event_id: int) -> Optional[Event]:
    db = get_db()
    cur = await db.execute("SELECT * FROM events WHERE id = ?", (event_id,))
    row = await cur.fetchone()
    return _row_to_event(row) if row else None


async def get_event_photos(event_id: int) -> list[str]:
    db = get_db()
    cur = await db.execute(
        "SELECT file_id FROM event_photos WHERE event_id = ? ORDER BY position ASC",
        (event_id,),
    )
    rows = await cur.fetchall()
    return [str(r["file_id"]) for r in rows]


async def get_pending_events(limit: int = 30) -> list[Event]:
    db = get_db()
    cur = await db.execute(
        "SELECT * FROM events WHERE status = 'pending' ORDER BY created_at ASC, id ASC LIMIT ?",
        (limit,),
    )
    rows = await cur.fetchall()
    return [_row_to_event(r) for r in rows]


async def set_event_status(event_id: int, status: str) -> bool:
    db = get_db()
    cur = await db.execute(
        "UPDATE events SET status = ? WHERE id = ?",
        (status, event_id),
    )
    await db.commit()
    return cur.rowcount > 0


# =========================
# Этап 4: организаторское "поднять"
# (минимально — обновляем created_at, чтобы в сортировках "по свежести" поднялось)
# =========================
async def get_organizer_events(organizer_id: int, limit: int = 10, status: str = "approved") -> list[Event]:
    db = get_db()
    cur = await db.execute(
        "SELECT * FROM events WHERE organizer_id = ? AND status = ? ORDER BY created_at DESC, id DESC LIMIT ?",
        (organizer_id, status, limit),
    )
    rows = await cur.fetchall()
    return [_row_to_event(r) for r in rows]


async def bump_event(event_id: int, organizer_id: int) -> tuple[bool, str]:
    """
    Возвращает (ok, reason). ok=True если подняли.
    Поднимать можно только СВОЁ и только approved.
    """
    ev = await get_event(event_id)
    if not ev:
        return False, "Событие не найдено"
    if int(ev.organizer_id) != int(organizer_id):
        return False, "Это не твоё событие"
    if ev.status != "approved":
        return False, "Поднимать можно только одобренные события"

    db = get_db()
    cur = await db.execute(
        "UPDATE events SET created_at = datetime('now') WHERE id = ?",
        (event_id,),
    )
    await db.commit()
    return (cur.rowcount > 0), ("OK" if cur.rowcount > 0 else "Не удалось обновить")


# =========================
# Удобный объект-адаптер (чтобы в хендлерах было repo.xxx)
# =========================
class Repo:
    async def ensure_user(self, user_id: int, role: str = "organizer") -> None:
        await ensure_user(user_id, role=role)

    async def create_event(self, **kwargs) -> int:
        return await create_event(**kwargs)

    async def get_event(self, event_id: int) -> Optional[Event]:
        return await get_event(event_id)

    async def get_event_photos(self, event_id: int) -> list[str]:
        return await get_event_photos(event_id)

    async def get_pending_events(self, limit: int = 30) -> list[Event]:
        return await get_pending_events(limit=limit)

    async def approve_event(self, event_id: int, admin_id: int | None = None) -> bool:
        return await set_event_status(event_id, "approved")

    async def reject_event(self, event_id: int, admin_id: int | None = None) -> bool:
        return await set_event_status(event_id, "rejected")

    async def get_organizer_events(self, organizer_id: int, limit: int = 10, status: str = "approved") -> list[Event]:
        return await get_organizer_events(organizer_id, limit=limit, status=status)

    async def bump_event(self, event_id: int, organizer_id: int) -> tuple[bool, str]:
        return await bump_event(event_id, organizer_id)


repo = Repo()