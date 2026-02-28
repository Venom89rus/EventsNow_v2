from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any, Optional, Sequence

from bot.db.database import get_db


# =========================
# MODELS
# =========================
@dataclass
class Event:
    id: int
    organizer_id: int
    category: str
    title: str
    description: str
    event_format: str
    start_date: Optional[str]
    end_date: Optional[str]
    start_time: Optional[str]
    end_time: Optional[str]
    location: str
    price_text: str
    ticket_link: str
    phone: str
    photo_ids: list[str]
    status: str

    # promo flags (optional)
    promoted_kind: Optional[str] = None  # "top" / "highlight" / "bump" ...
    is_top: int = 0
    is_highlight: int = 0
    promoted_at: Optional[str] = None


@dataclass
class PromoOrder:
    id: int
    organizer_id: int
    event_id: int
    service: str
    amount: int
    currency: str
    status: str
    payload_json: dict[str, Any]
    created_at: str
    paid_at: Optional[str] = None
    yk_payment_id: Optional[str] = None


# =========================
# HELPERS
# =========================
def _col(row: Any, name: str, default: Any = None) -> Any:
    """sqlite3.Row / aiosqlite.Row safe accessor."""
    try:
        return row[name]
    except Exception:
        return default


def _json_loads_safe(s: Any, default: Any):
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


async def _table_info(table: str) -> set[str]:
    """
    Returns set of column names for a table.
    IMPORTANT: uses aiosqlite cursor; must await execute/fetchall.
    """
    db = get_db()  # NO await here!
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    # rows: cid, name, type, notnull, dflt_value, pk
    return {r[1] for r in rows}


def _row_to_event(row: Any) -> Event:
    photo_ids_raw = _col(row, "photo_ids", None)
    photos = _json_loads_safe(photo_ids_raw, [])
    if not isinstance(photos, list):
        photos = []

    # поддержка старых колонок event_date/event_time
    start_date = _col(row, "start_date", None)
    start_time = _col(row, "start_time", None)
    if not start_date:
        start_date = _col(row, "event_date", None)
    if not start_time:
        start_time = _col(row, "event_time", None)

    end_date = _col(row, "end_date", None)
    end_time = _col(row, "end_time", None)
    if not end_date:
        end_date = start_date
    if not end_time:
        end_time = start_time

    return Event(
        id=int(_col(row, "id", 0) or 0),
        organizer_id=int(_col(row, "organizer_id", 0) or 0),
        category=str(_col(row, "category", "") or ""),
        title=str(_col(row, "title", "") or ""),
        description=str(_col(row, "description", "") or ""),
        event_format=str(_col(row, "event_format", "single") or "single"),
        start_date=str(start_date) if start_date is not None else None,
        end_date=str(end_date) if end_date is not None else None,
        start_time=str(start_time) if start_time is not None else None,
        end_time=str(end_time) if end_time is not None else None,
        location=str(_col(row, "location", "") or ""),
        price_text=str(_col(row, "price_text", "") or ""),
        ticket_link=str(_col(row, "ticket_link", "") or ""),
        phone=str(_col(row, "phone", "") or ""),
        photo_ids=photos,
        status=str(_col(row, "status", "") or ""),
        promoted_kind=str(_col(row, "promoted_kind", "") or "") or None,
        is_top=int(_col(row, "is_top", 0) or 0),
        is_highlight=int(_col(row, "is_highlight", 0) or 0),
        promoted_at=str(_col(row, "promoted_at", "") or "") or None,
    )


def _row_to_order(row: Any) -> PromoOrder:
    payload = _json_loads_safe(_col(row, "payload_json", "{}"), {})
    if not isinstance(payload, dict):
        payload = {}
    return PromoOrder(
        id=int(_col(row, "id", 0) or 0),
        organizer_id=int(_col(row, "organizer_id", 0) or 0),
        event_id=int(_col(row, "event_id", 0) or 0),
        service=str(_col(row, "service", "") or ""),
        amount=int(_col(row, "amount", 0) or 0),
        currency=str(_col(row, "currency", "RUB") or "RUB"),
        status=str(_col(row, "status", "new") or "new"),
        payload_json=payload,
        created_at=str(_col(row, "created_at", "") or ""),
        paid_at=str(_col(row, "paid_at", "") or "") or None,
        yk_payment_id=str(_col(row, "yk_payment_id", "") or "") or None,
    )


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# =========================
# CORE REPO API
# =========================
async def ensure_user(user_id: int) -> None:
    db = get_db()
    ucols = await _table_info("users")

    # поддержка старых схем: где user_id вместо id
    if "user_id" in ucols and "id" not in ucols:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (int(user_id),),
        )
    else:
        await db.execute(
            "INSERT OR IGNORE INTO users (id) VALUES (?)",
            (int(user_id),),
        )
    await db.commit()


async def create_event(
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
    photo_ids: Sequence[str],
    status: str = "pending",
) -> int:
    db = get_db()
    ecols = await _table_info("events")

    payload_photos = json.dumps(list(photo_ids or []), ensure_ascii=False)

    fields: list[str] = []
    values: list[Any] = []

    def add(col: str, val: Any):
        if col in ecols:
            fields.append(col)
            values.append(val)

    add("organizer_id", int(organizer_id))
    add("category", str(category))
    add("title", str(title))
    add("description", str(description))
    add("event_format", str(event_format))

    # новые колонки
    add("start_date", str(start_date))
    add("end_date", str(end_date))
    add("start_time", str(start_time))
    add("end_time", str(end_time))

    # старые колонки (если есть только они)
    if "start_date" not in ecols and "event_date" in ecols:
        add("event_date", str(start_date))
    if "start_time" not in ecols and "event_time" in ecols:
        add("event_time", str(start_time))

    add("location", str(location))
    add("price_text", str(price_text))
    add("ticket_link", str(ticket_link))
    add("phone", str(phone))

    # если в events есть photo_ids — пишем туда (старый вариант схемы)
    add("photo_ids", payload_photos)

    add("status", str(status))

    if not fields:
        raise RuntimeError("events table has no compatible columns")

    placeholders = ",".join(["?"] * len(fields))
    sql = f"INSERT INTO events ({','.join(fields)}) VALUES ({placeholders})"

    cur = await db.execute(sql, tuple(values))
    event_id = int(cur.lastrowid)

    # ✅ НОВОЕ: если колонки photo_ids в events НЕТ — сохраняем фото в event_photos
    if "photo_ids" not in ecols and photo_ids:
        try:
            pcols = await _table_info("event_photos")
        except Exception:
            pcols = set()

        # таблица существует и есть нужные колонки
        if pcols and ("event_id" in pcols) and ("file_id" in pcols):
            # подчистим старые на всякий случай (если вдруг переиспользование)
            await db.execute("DELETE FROM event_photos WHERE event_id = ?", (event_id,))
            pos = 1
            for fid in list(photo_ids):
                if not fid:
                    continue
                # position может отсутствовать в старой схеме — проверим
                if "position" in pcols:
                    await db.execute(
                        "INSERT INTO event_photos (event_id, file_id, position) VALUES (?, ?, ?)",
                        (event_id, str(fid), pos),
                    )
                else:
                    await db.execute(
                        "INSERT INTO event_photos (event_id, file_id) VALUES (?, ?)",
                        (event_id, str(fid)),
                    )
                pos += 1

    await db.commit()
    return event_id

async def get_event(event_id: int) -> Optional[Event]:
    db = get_db()
    cur = await db.execute("SELECT * FROM events WHERE id = ?", (int(event_id),))
    row = await cur.fetchone()
    return _row_to_event(row) if row else None


async def get_event_photos(event_id: int) -> list[str]:
    ev = await get_event(event_id)
    if not ev:
        return []

    # если в объекте уже есть photo_ids (старая схема) — используем
    if getattr(ev, "photo_ids", None):
        return list(ev.photo_ids or [])

    # иначе читаем из event_photos (твоя текущая схема)
    db = get_db()
    try:
        cur = await db.execute(
            "SELECT file_id FROM event_photos WHERE event_id = ? ORDER BY position ASC, id ASC",
            (int(event_id),),
        )
        rows = await cur.fetchall()
        return [r["file_id"] if isinstance(r, dict) else r[0] for r in rows]
    except Exception:
        return []

async def get_pending_events(limit: int = 30) -> list[Event]:
    db = get_db()
    cur = await db.execute(
        "SELECT * FROM events WHERE status = 'pending' ORDER BY id DESC LIMIT ?",
        (int(limit),),
    )
    rows = await cur.fetchall()
    return [_row_to_event(r) for r in rows]


async def set_event_status(event_id: int, status: str) -> None:
    db = get_db()
    await db.execute(
        "UPDATE events SET status = ? WHERE id = ?",
        (str(status), int(event_id)),
    )
    await db.commit()


async def get_organizer_events(organizer_id: int, limit: int = 10, status: Optional[str] = None) -> list[Event]:
    db = get_db()
    if status:
        cur = await db.execute(
            "SELECT * FROM events WHERE organizer_id = ? AND status = ? ORDER BY id DESC LIMIT ?",
            (int(organizer_id), str(status), int(limit)),
        )
    else:
        cur = await db.execute(
            "SELECT * FROM events WHERE organizer_id = ? ORDER BY id DESC LIMIT ?",
            (int(organizer_id), int(limit)),
        )
    rows = await cur.fetchall()
    return [_row_to_event(r) for r in rows]


# =========================
# PROMO ORDERS
# =========================
async def create_promo_order(
    organizer_id: int,
    event_id: int,
    service: str,
    amount: int,
    currency: str = "RUB",
    payload: Optional[dict[str, Any]] = None,
) -> int:
    """
    service: 'top' | 'highlight' | 'bump' | ...
    """
    db = get_db()
    ocols = await _table_info("promo_orders")

    created_at = _now_iso()
    payload_json = json.dumps(payload or {}, ensure_ascii=False)

    fields: list[str] = []
    values: list[Any] = []

    def add(col: str, val: Any):
        if col in ocols:
            fields.append(col)
            values.append(val)

    add("organizer_id", int(organizer_id))
    add("event_id", int(event_id))
    add("service", str(service))
    add("amount", int(amount))
    add("currency", str(currency))
    add("status", "new")
    add("payload_json", payload_json)
    add("created_at", created_at)

    placeholders = ",".join(["?"] * len(fields))
    sql = f"INSERT INTO promo_orders ({','.join(fields)}) VALUES ({placeholders})"

    cur = await db.execute(sql, tuple(values))
    await db.commit()
    return int(cur.lastrowid)

async def get_order(order_id: int) -> Optional[PromoOrder]:
    db = get_db()
    cur = await db.execute("SELECT * FROM promo_orders WHERE id = ?", (int(order_id),))
    row = await cur.fetchone()
    return _row_to_order(row) if row else None

async def mark_order_paid(order_id: int, yk_payment_id: Optional[str] = None) -> None:
    db = get_db()
    ocols = await _table_info("promo_orders")
    paid_at = _now_iso()

    if "yk_payment_id" in ocols:
        await db.execute(
            "UPDATE promo_orders SET status = 'paid', paid_at = ?, yk_payment_id = ? WHERE id = ?",
            (paid_at, yk_payment_id, int(order_id)),
        )
    else:
        await db.execute(
            "UPDATE promo_orders SET status = 'paid', paid_at = ? WHERE id = ?",
            (paid_at, int(order_id)),
        )

    await db.commit()

async def set_event_promoted(event_id: int, kind: str) -> None:
    """
    Ставим флаги промо на событие так, чтобы лента могла показывать проплаченные.
    kind: 'top' | 'highlight' | 'bump' | 'notify' ...
    """
    db = get_db()
    ecols = await _table_info("events")
    now = _now_iso()

    updates: dict[str, object] = {}

    if kind == "top" and "is_top" in ecols:
        updates["is_top"] = 1
    elif kind == "highlight" and "is_highlight" in ecols:
        updates["is_highlight"] = 1

    if "promoted_kind" in ecols:
        updates["promoted_kind"] = str(kind)

    if "promoted_at" in ecols:
        updates["promoted_at"] = now

    if not updates:
        return

    set_sql = ", ".join([f"{k} = ?" for k in updates.keys()])
    params = list(updates.values()) + [int(event_id)]

    await db.execute(f"UPDATE events SET {set_sql} WHERE id = ?", params)
    await db.commit()

async def get_promoted_events_feed(limit: int = 10) -> list[Event]:
    """
    Лента жителя: только approved + только проплаченные/промо.
    Приоритет:
      1) ТОП (is_top=1)
      2) Подсветка (is_highlight=1)
      3) Остальные промо (promoted_at / promoted_kind)
    """
    db = get_db()
    ecols = await _table_info("events")

    where_parts = ["status = 'approved'"]
    promo_parts: list[str] = []

    if "is_top" in ecols:
        promo_parts.append("is_top = 1")
    if "is_highlight" in ecols:
        promo_parts.append("is_highlight = 1")
    if "promoted_at" in ecols:
        promo_parts.append("promoted_at IS NOT NULL")
    if "promoted_kind" in ecols:
        promo_parts.append("promoted_kind IS NOT NULL AND promoted_kind != ''")

    # если в events вообще нет промо-колонок — пробуем через promo_orders
    if not promo_parts:
        # fallback: через paid orders
        cur = await db.execute(
            """
            SELECT e.*
            FROM events e
            JOIN promo_orders p ON p.event_id = e.id
            WHERE e.status='approved' AND p.status='paid'
            ORDER BY p.paid_at DESC, e.id DESC
            LIMIT ?
            """,
            (int(limit),),
        )
        rows = await cur.fetchall()
        return [_row_to_event(r) for r in rows]

    where_parts.append("(" + " OR ".join(promo_parts) + ")")

    # сортировка: ТОП выше, затем highlight, затем по promoted_at desc, затем по id
    order_parts: list[str] = []
    if "is_top" in ecols:
        order_parts.append("is_top DESC")
    if "is_highlight" in ecols:
        order_parts.append("is_highlight DESC")
    if "promoted_at" in ecols:
        order_parts.append("promoted_at DESC")
    order_parts.append("id DESC")

    sql = f"""
        SELECT *
        FROM events
        WHERE {' AND '.join(where_parts)}
        ORDER BY {', '.join(order_parts)}
        LIMIT ?
    """

    cur = await db.execute(sql, (int(limit),))
    rows = await cur.fetchall()
    return [_row_to_event(r) for r in rows]

# =========================
# Repo wrapper (как у тебя в коде)
# =========================
class Repo:
    async def ensure_user(self, user_id: int, role: str = "resident") -> None:
        """
        Гарантирует наличие пользователя в таблице users.
        Если пользователь уже есть — при необходимости обновит роль.

        Важно: хендлеры вызывают ensure_user(..., role="organizer"),
        поэтому роль должна приниматься параметром.
        """
        db = get_db()

        # 1) пробуем вставить
        await db.execute(
            "INSERT OR IGNORE INTO users(user_id, role) VALUES(?, ?)",
            (int(user_id), str(role)),
        )

        # 2) если уже был — обновим роль (чтобы organizer/resident корректно фиксировались)
        await db.execute(
            "UPDATE users SET role = ? WHERE user_id = ?",
            (str(role), int(user_id)),
        )

        await db.commit()

    async def create_event(self, **kwargs) -> int:
        """
        Создаёт событие.

        Важно: афиши хранятся в таблице event_photos (а не в events.photo_ids, которого может не быть).
        Поэтому если хендлер передал photo_ids (или photos) — создаём событие через core create_event(...),
        который поддерживает обе схемы (events.photo_ids / event_photos).

        Для обратной совместимости оставляем fallback на INSERT только по колонкам events.
        """

        # --- 1) Нормальный путь: создание с поддержкой афиш ---
        photo_ids = kwargs.get("photo_ids")
        if photo_ids is None:
            photo_ids = kwargs.get("photos")

        looks_like_full_event = all(
            k in kwargs and kwargs.get(k) not in (None, "")
            for k in ("organizer_id", "category", "title", "description")
        )

        if looks_like_full_event:
            organizer_id = int(kwargs.get("organizer_id"))
            category = str(kwargs.get("category") or "")
            title = str(kwargs.get("title") or "")
            description = str(kwargs.get("description") or "")
            event_format = str(kwargs.get("event_format") or kwargs.get("format") or "")

            start_date = (
                    kwargs.get("start_date")
                    or kwargs.get("date_from")
                    or kwargs.get("event_date")
                    or ""
            )
            end_date = (
                    kwargs.get("end_date")
                    or kwargs.get("date_to")
                    or kwargs.get("event_date")
                    or ""
            )
            start_time = (
                    kwargs.get("start_time")
                    or kwargs.get("time_from")
                    or kwargs.get("event_time")
                    or ""
            )
            end_time = (
                    kwargs.get("end_time")
                    or kwargs.get("time_to")
                    or kwargs.get("event_time")
                    or ""
            )

            location = str(kwargs.get("location") or "")
            price_text = str(kwargs.get("price_text") or kwargs.get("price") or "")
            ticket_link = str(kwargs.get("ticket_link") or kwargs.get("link") or "")
            phone = str(kwargs.get("phone") or "")
            status = str(kwargs.get("status") or "pending")

            # нормализуем список фото
            if photo_ids is None:
                photo_ids_list = []
            elif isinstance(photo_ids, (list, tuple)):
                photo_ids_list = [str(x) for x in photo_ids if x]
            else:
                photo_ids_list = [str(photo_ids)] if str(photo_ids).strip() else []

            return await create_event(
                organizer_id=organizer_id,
                category=category,
                title=title,
                description=description,
                event_format=event_format,
                start_date=str(start_date),
                end_date=str(end_date),
                start_time=str(start_time),
                end_time=str(end_time),
                location=location,
                price_text=price_text,
                ticket_link=ticket_link,
                phone=phone,
                photo_ids=photo_ids_list,
                status=status,
            )

        # --- 2) Fallback: старое поведение (если кто-то создаёт событие "кусочками") ---
        db = get_db()

        cur = await db.execute("PRAGMA table_info(events)")
        rows = await cur.fetchall()
        cols = {r["name"] for r in rows}

        if "organizer_id" not in kwargs:
            raise ValueError("create_event: missing required field 'organizer_id'")

        data = {k: v for k, v in kwargs.items() if k in cols}

        if "event_date" in kwargs and "event_date" not in cols and "start_date" in cols and "start_date" not in data:
            data["start_date"] = kwargs["event_date"]

        if not data:
            raise ValueError("create_event: nothing to insert (no matching columns)")

        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        values = list(data.values())

        cur2 = await db.execute(
            f"INSERT INTO events ({columns}) VALUES ({placeholders})",
            values,
        )
        await db.commit()
        return int(cur2.lastrowid)

    async def get_event(self, event_id: int) -> Optional[Event]:
        return await get_event(event_id)

    async def get_event_photos(self, event_id: int) -> list[str]:
        return await get_event_photos(event_id)

    async def get_pending_events(self, limit: int = 30) -> list[Event]:
        return await get_pending_events(limit=limit)

    async def get_organizer_events(self, organizer_id: int, limit: int = 10, status: Optional[str] = None) -> list[Event]:
        return await get_organizer_events(organizer_id=organizer_id, limit=limit, status=status)

    async def create_promo_order(
            self,
            organizer_id: int,
            event_id: int,
            service: str,
            amount_rub: int | None = None,
            amount: int | None = None,
            currency: str = "RUB",
            payload_json: str = "{}",
    ) -> int:
        """
        Совместимость:
        - старый код мог передавать amount_rub
        - новый/другой код мог передавать amount
        """
        amt = amount_rub if amount_rub is not None else (amount if amount is not None else 0)

        db = get_db()  # ВАЖНО: без await (у тебя это уже всплывало с threads can only be started once)
        cur = await db.execute(
            """
            INSERT INTO promo_orders(organizer_id, event_id, service, amount, currency, status, provider, payload_json)
            VALUES(?, ?, ?, ?, ?, 'created', 'yookassa', ?)
            """,
            (int(organizer_id), int(event_id), str(service), int(amt), str(currency), str(payload_json)),
        )
        await db.commit()
        return int(cur.lastrowid)

    async def set_order_payload(self, order_id: int, payload: object) -> None:
        """
        Сохраняет payload (ответ YooKassa) в promo_orders.payload_json.
        Если в таблице есть колонка yk_payment_id — положит туда payment.id.
        Статусы/paid_at НЕ трогает.
        """
        import json
        import datetime
        import decimal
        from bot.db.database import get_db

        db = get_db()

        # узнаем колонки promo_orders
        cur = await db.execute("PRAGMA table_info(promo_orders)")
        rows = await cur.fetchall()

        def _colname(r):
            try:
                # aiosqlite.Row поддерживает доступ по индексу
                return r[1]
            except Exception:
                try:
                    return r.get("name")
                except Exception:
                    return None

        cols = {c for c in (_colname(r) for r in rows) if c}

        # ---- нормализация payload -> JSON-friendly ----
        def _to_jsonable(obj, *, _depth=0, _seen=None):
            if _seen is None:
                _seen = set()

            # ограничим глубину, чтобы не зависнуть на циклических структурах
            if _depth > 8:
                return str(obj)

            # None / базовые типы
            if obj is None or isinstance(obj, (str, int, float, bool)):
                return obj

            # Decimal -> str (или float, но str безопаснее)
            if isinstance(obj, decimal.Decimal):
                return str(obj)

            # date/datetime -> ISO
            if isinstance(obj, (datetime.datetime, datetime.date)):
                try:
                    return obj.isoformat()
                except Exception:
                    return str(obj)

            # bytes -> decode
            if isinstance(obj, (bytes, bytearray)):
                try:
                    return obj.decode("utf-8", errors="replace")
                except Exception:
                    return str(obj)

            obj_id = id(obj)
            if obj_id in _seen:
                return "<recursive>"
            _seen.add(obj_id)

            # dict
            if isinstance(obj, dict):
                return {
                    str(k): _to_jsonable(v, _depth=_depth + 1, _seen=_seen)
                    for k, v in obj.items()
                }

            # list/tuple/set
            if isinstance(obj, (list, tuple, set)):
                return [_to_jsonable(v, _depth=_depth + 1, _seen=_seen) for v in obj]

            # YooKassa SDK часто умеет отдавать dict
            for meth in ("to_dict", "dict", "json"):
                if hasattr(obj, meth) and callable(getattr(obj, meth)):
                    try:
                        val = getattr(obj, meth)()
                        # .json() иногда возвращает строку JSON — попробуем распарсить
                        if isinstance(val, str):
                            try:
                                return json.loads(val)
                            except Exception:
                                return val
                        return _to_jsonable(val, _depth=_depth + 1, _seen=_seen)
                    except Exception:
                        pass

            # __dict__
            try:
                d = vars(obj)
                return _to_jsonable(d, _depth=_depth + 1, _seen=_seen)
            except Exception:
                pass

            # fallback
            return str(obj)

        data = _to_jsonable(payload)

        # payment_id достаём максимально мягко
        payment_id = None
        if isinstance(data, dict):
            payment_id = data.get("id") or data.get("payment_id")
            # если payload наш (с ключом raw)
            if not payment_id and isinstance(data.get("raw"), dict):
                payment_id = data["raw"].get("id")

        payload_json = json.dumps(data, ensure_ascii=False)

        if "yk_payment_id" in cols:
            await db.execute(
                "UPDATE promo_orders SET payload_json = ?, yk_payment_id = ? WHERE id = ?",
                (payload_json, payment_id, int(order_id)),
            )
        else:
            await db.execute(
                "UPDATE promo_orders SET payload_json = ? WHERE id = ?",
                (payload_json, int(order_id)),
            )

        await db.commit()

    async def set_promo_payment_data(self, order_id: int, payment_id: str, confirmation_url: str,
                                     payload_json: str) -> None:
        db = get_db()
        await db.execute(
            """
            UPDATE promo_orders
            SET payload_json = ?
            WHERE id = ?
            """,
            (payload_json, int(order_id)),
        )
        await db.commit()
    async def mark_promo_paid(self, order_id: int) -> None:
        db = get_db()
        await db.execute(
            "UPDATE promo_orders SET status='paid', paid_at=datetime('now') WHERE id=?",
            (int(order_id),),
        )
        await db.commit()

    async def get_order(self, order_id: int) -> Optional[PromoOrder]:
        return await get_order(order_id)

    async def mark_order_paid(self, order_id: int, yk_payment_id: Optional[str] = None) -> None:
        return await mark_order_paid(order_id=order_id, yk_payment_id=yk_payment_id)

    async def set_event_promoted(self, event_id: int, kind: str) -> None:
        return await set_event_promoted(event_id=event_id, kind=kind)

    async def get_promoted_events_feed(self, limit: int = 10) -> list[Event]:
        return await get_promoted_events_feed(limit=limit)

    async def get_event_by_id(self, event_id: int) -> Optional[Any]:
        db = get_db()
        cur = await db.execute("SELECT * FROM events WHERE id = ? LIMIT 1", (int(event_id),))
        row = await cur.fetchone()
        return row

    async def delete_event(self, event_id: int) -> bool:
        """
        Удаляем событие и привязанные промо-заказы (если есть).
        Ничего лишнего не трогаем.
        """
        db = get_db()

        # проверим существование
        cur = await db.execute("SELECT id FROM events WHERE id = ? LIMIT 1", (int(event_id),))
        row = await cur.fetchone()
        if not row:
            return False

        # promo_orders может быть, а может нет — делаем безопасно
        try:
            await db.execute("DELETE FROM promo_orders WHERE event_id = ?", (int(event_id),))
        except Exception:
            pass

        await db.execute("DELETE FROM events WHERE id = ?", (int(event_id),))
        await db.commit()
        return True

    async def set_event_status(self, event_id: int, status: str) -> bool:
        """
        Меняет статус события.
        ВАЖНО: get_db() НЕ await-им, иначе aiosqlite падает "threads can only be started once".
        """
        db = get_db()
        cur = await db.execute(
            """
            UPDATE events
               SET status = ?,
                   updated_at = datetime('now')
             WHERE id = ?
            """,
            (status, int(event_id)),
        )
        await db.commit()
        return (cur.rowcount or 0) > 0

    async def approve_event(self, event_id: int, admin_id: int | None = None) -> bool:
        # admin_id оставляем в сигнатуре, чтобы не ломать handler’ы
        return await self.set_event_status(event_id, "approved")

    async def reject_event(self, event_id: int, admin_id: int | None = None) -> bool:
        return await self.set_event_status(event_id, "rejected")

def _parse_date_any(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    s = str(s).strip()
    if not s or s.lower() == "none":
        return None

    # dd.mm.yyyy
    try:
        return datetime.strptime(s, "%d.%m.%Y").date()
    except Exception:
        pass

    # yyyy-mm-dd
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        pass

    return None

def _event_is_actual(row: Any, today: Optional[date] = None) -> bool:
    """
    Событие актуально, если:
    - есть end_date и она >= сегодня
    - иначе start_date/event_date >= сегодня
    """
    if today is None:
        today = date.today()

    # row может быть sqlite3.Row или dict-подобный объект
    def col(name: str, default: Any = None) -> Any:
        try:
            return row[name]
        except Exception:
            return default

    end_d = _parse_date_any(col("end_date")) or _parse_date_any(col("date_to"))
    start_d = (
        _parse_date_any(col("start_date"))
        or _parse_date_any(col("event_date"))
        or _parse_date_any(col("date_from"))
    )

    if end_d:
        return end_d >= today
    if start_d:
        return start_d >= today

    # если дат нет — лучше не показывать жителю
    return False


repo = Repo()