from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from bot.db.database import get_db


# =========================
# MODELS
# =========================

@dataclass(slots=True)
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
    created_at: str | None

    photo_ids: list[str]


@dataclass(slots=True)
class PromoOrder:
    id: int
    organizer_id: int
    event_id: int
    service: str
    amount_rub: int
    status: str
    payload: dict[str, Any]
    created_at: str | None
    paid_at: str | None


# =========================
# HELPERS
# =========================

def _col(row: Any, name: str, default: Any = None) -> Any:
    """sqlite3.Row / aiosqlite.Row не поддерживает .get()"""
    try:
        v = row[name]
    except Exception:
        return default
    return default if v is None else v


def _json_load(s: Any, default: Any) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


# =========================
# REPO
# =========================

class Repo:
    # ---------- users ----------
    async def ensure_user(self, user_id: int, role: str = "organizer") -> None:
        db = get_db()
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, role) VALUES (?, ?)",
            (int(user_id), role),
        )
        await db.commit()

    # ---------- events ----------
    async def create_event(
        self,
        *,
        organizer_id: int,
        category: str,
        title: str,
        description: str,
        event_format: str,
        location: str,
        price_text: str,
        ticket_link: str,
        phone: str,
        status: str = "pending",
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
        # photos
        photo_ids: Sequence[str] | None = None,
    ) -> int:
        db = get_db()

        cur = await db.execute(
            """
            INSERT INTO events (
                organizer_id, category, title, description, event_format,
                event_date, event_time,
                start_date, end_date, open_time, close_time,
                sessions_start_date, sessions_end_date, sessions_times,
                location, price_text, ticket_link, phone, status
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            (
                int(organizer_id),
                category,
                title,
                description,
                event_format,
                event_date,
                event_time,
                start_date,
                end_date,
                open_time,
                close_time,
                sessions_start_date,
                sessions_end_date,
                sessions_times,
                location,
                price_text,
                ticket_link,
                phone,
                status,
            ),
        )
        await db.commit()
        event_id = int(cur.lastrowid)

        # photos
        if photo_ids:
            for pos, file_id in enumerate(list(photo_ids)[:5], start=1):
                await db.execute(
                    "INSERT INTO event_photos (event_id, file_id, position) VALUES (?, ?, ?)",
                    (event_id, str(file_id), pos),
                )
            await db.commit()

        return event_id

    async def set_event_status(self, event_id: int, status: str) -> bool:
        db = get_db()
        cur = await db.execute(
            "UPDATE events SET status=? WHERE id=?",
            (status, int(event_id)),
        )
        await db.commit()
        return cur.rowcount > 0

    async def approve_event(self, event_id: int, admin_id: int | None = None) -> bool:
        # admin_id оставляем для совместимости (можно логировать позже)
        return await self.set_event_status(event_id, "approved")

    async def reject_event(self, event_id: int, admin_id: int | None = None) -> bool:
        return await self.set_event_status(event_id, "rejected")

    async def get_event_photos(self, event_id: int) -> list[str]:
        db = get_db()
        cur = await db.execute(
            "SELECT file_id FROM event_photos WHERE event_id=? ORDER BY position ASC",
            (int(event_id),),
        )
        rows = await cur.fetchall()
        return [str(r[0]) for r in rows]

    async def get_event(self, event_id: int) -> Optional[Event]:
        db = get_db()
        cur = await db.execute("SELECT * FROM events WHERE id=?", (int(event_id),))
        row = await cur.fetchone()
        if not row:
            return None
        eid = int(_col(row, "id", 0))
        photos = await self.get_event_photos(eid)
        return Event(
            id=eid,
            organizer_id=int(_col(row, "organizer_id", 0)),
            category=str(_col(row, "category", "")),
            title=str(_col(row, "title", "")),
            description=str(_col(row, "description", "")),
            event_format=str(_col(row, "event_format", "single")),
            event_date=_col(row, "event_date"),
            event_time=_col(row, "event_time"),
            start_date=_col(row, "start_date"),
            end_date=_col(row, "end_date"),
            open_time=_col(row, "open_time"),
            close_time=_col(row, "close_time"),
            sessions_start_date=_col(row, "sessions_start_date"),
            sessions_end_date=_col(row, "sessions_end_date"),
            sessions_times=_col(row, "sessions_times"),
            location=str(_col(row, "location", "")),
            price_text=str(_col(row, "price_text", "")),
            ticket_link=str(_col(row, "ticket_link", "")),
            phone=str(_col(row, "phone", "")),
            status=str(_col(row, "status", "pending")),
            created_at=_col(row, "created_at"),
            photo_ids=photos,
        )

    async def get_pending_events(self, limit: int = 20) -> list[Event]:
        db = get_db()
        cur = await db.execute(
            "SELECT * FROM events WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
            (int(limit),),
        )
        rows = await cur.fetchall()
        events: list[Event] = []
        for r in rows:
            eid = int(_col(r, "id", 0))
            photos = await self.get_event_photos(eid)
            events.append(
                Event(
                    id=eid,
                    organizer_id=int(_col(r, "organizer_id", 0)),
                    category=str(_col(r, "category", "")),
                    title=str(_col(r, "title", "")),
                    description=str(_col(r, "description", "")),
                    event_format=str(_col(r, "event_format", "single")),
                    event_date=_col(r, "event_date"),
                    event_time=_col(r, "event_time"),
                    start_date=_col(r, "start_date"),
                    end_date=_col(r, "end_date"),
                    open_time=_col(r, "open_time"),
                    close_time=_col(r, "close_time"),
                    sessions_start_date=_col(r, "sessions_start_date"),
                    sessions_end_date=_col(r, "sessions_end_date"),
                    sessions_times=_col(r, "sessions_times"),
                    location=str(_col(r, "location", "")),
                    price_text=str(_col(r, "price_text", "")),
                    ticket_link=str(_col(r, "ticket_link", "")),
                    phone=str(_col(r, "phone", "")),
                    status=str(_col(r, "status", "pending")),
                    created_at=_col(r, "created_at"),
                    photo_ids=photos,
                )
            )
        return events

    async def get_organizer_events(
        self,
        organizer_id: int,
        limit: int = 10,
        status: str = "approved",
    ) -> list[Event]:
        db = get_db()
        cur = await db.execute(
            "SELECT * FROM events WHERE organizer_id=? AND status=? ORDER BY created_at DESC LIMIT ?",
            (int(organizer_id), status, int(limit)),
        )
        rows = await cur.fetchall()
        out: list[Event] = []
        for r in rows:
            eid = int(_col(r, "id", 0))
            photos = await self.get_event_photos(eid)
            out.append(
                Event(
                    id=eid,
                    organizer_id=int(_col(r, "organizer_id", 0)),
                    category=str(_col(r, "category", "")),
                    title=str(_col(r, "title", "")),
                    description=str(_col(r, "description", "")),
                    event_format=str(_col(r, "event_format", "single")),
                    event_date=_col(r, "event_date"),
                    event_time=_col(r, "event_time"),
                    start_date=_col(r, "start_date"),
                    end_date=_col(r, "end_date"),
                    open_time=_col(r, "open_time"),
                    close_time=_col(r, "close_time"),
                    sessions_start_date=_col(r, "sessions_start_date"),
                    sessions_end_date=_col(r, "sessions_end_date"),
                    sessions_times=_col(r, "sessions_times"),
                    location=str(_col(r, "location", "")),
                    price_text=str(_col(r, "price_text", "")),
                    ticket_link=str(_col(r, "ticket_link", "")),
                    phone=str(_col(r, "phone", "")),
                    status=str(_col(r, "status", "pending")),
                    created_at=_col(r, "created_at"),
                    photo_ids=photos,
                )
            )
        return out

    # ---------- promo orders ----------
    async def create_promo_order(
        self,
        *,
        organizer_id: int,
        event_id: int,
        service: str,
        amount_rub: int,
        payload: dict[str, Any] | None = None,
    ) -> int:
        db = get_db()
        payload_json = json.dumps(payload or {}, ensure_ascii=False)

        cur = await db.execute(
            """
            INSERT INTO promo_orders (
                organizer_id, event_id, service, amount_rub, status, payload_json
            ) VALUES (?, ?, ?, ?, 'created', ?)
            """,
            (int(organizer_id), int(event_id), str(service), int(amount_rub), payload_json),
        )
        await db.commit()
        return int(cur.lastrowid)

    async def get_order(self, order_id: int) -> Optional[dict[str, Any]]:
        """
        ВАЖНО: promo.py сейчас ожидает dict и обращается order["organizer_id"].
        Поэтому возвращаем dict, а не dataclass.
        """
        db = get_db()
        cur = await db.execute("SELECT * FROM promo_orders WHERE id=?", (int(order_id),))
        row = await cur.fetchone()
        if not row:
            return None
        return {
            "id": int(_col(row, "id", 0)),
            "organizer_id": int(_col(row, "organizer_id", 0)),
            "event_id": int(_col(row, "event_id", 0)),
            "service": str(_col(row, "service", "")),
            "amount_rub": int(_col(row, "amount_rub", 0)),
            "status": str(_col(row, "status", "created")),
            "payload": _json_load(_col(row, "payload_json", "{}"), {}),
            "created_at": _col(row, "created_at"),
            "paid_at": _col(row, "paid_at"),
        }

    async def set_order_status(self, order_id: int, status: str) -> bool:
        db = get_db()
        cur = await db.execute(
            "UPDATE promo_orders SET status=? WHERE id=?",
            (status, int(order_id)),
        )
        await db.commit()
        return cur.rowcount > 0

    async def mark_order_paid(self, order_id: int) -> bool:
        db = get_db()
        cur = await db.execute(
            "UPDATE promo_orders SET status='paid', paid_at=datetime('now') WHERE id=?",
            (int(order_id),),
        )
        await db.commit()
        return cur.rowcount > 0

    async def set_event_promoted(self, event_id: int, kind: str) -> bool:
        """
        promo.py ожидает этот метод.
        kind = service из promo_orders (например: 'top', 'broadcast', ...)
        """
        db = get_db()

        # Простая логика длительности. Можем расширить позже.
        days = 7 if kind == "top" else 0

        if days > 0:
            cur = await db.execute(
                """
                UPDATE events
                SET promoted_kind=?,
                    promoted_at=datetime('now'),
                    promoted_until=datetime('now', ?)
                WHERE id=?
                """,
                (str(kind), f"+{int(days)} days", int(event_id)),
            )
        else:
            # услуги без "срока" — просто фиксируем факт
            cur = await db.execute(
                """
                UPDATE events
                SET promoted_kind=?,
                    promoted_at=datetime('now')
                WHERE id=?
                """,
                (str(kind), int(event_id)),
            )

        await db.commit()
        return cur.rowcount > 0

# =========================
# SINGLETON + BACKWARD API
# =========================

repo = Repo()

# чтобы не ломать старые импорты:
async def ensure_user(user_id: int, role: str = "organizer") -> None:
    await repo.ensure_user(user_id, role=role)

async def create_event(**kwargs: Any) -> int:
    return await repo.create_event(**kwargs)

async def get_pending_events(limit: int = 20) -> list[Event]:
    return await repo.get_pending_events(limit=limit)

async def get_event(event_id: int) -> Optional[Event]:
    return await repo.get_event(event_id)

async def approve_event(event_id: int, admin_id: int) -> bool:
    return await repo.approve_event(event_id, admin_id=admin_id)

async def reject_event(event_id: int, admin_id: int) -> bool:
    return await repo.reject_event(event_id, admin_id=admin_id)