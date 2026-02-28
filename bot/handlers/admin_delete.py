from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from bot.config import ADMIN_IDS
from bot.db.database import get_db


router = Router()


class AdminDelete(StatesGroup):
    waiting_event_id = State()


def _parse_admin_ids(value) -> set[int]:
    """
    ADMIN_IDS может быть:
    - list[int]
    - list[str]
    - строка "1,2,3"
    """
    if value is None:
        return set()

    if isinstance(value, (list, tuple, set)):
        out = set()
        for x in value:
            try:
                out.add(int(x))
            except Exception:
                pass
        return out

    if isinstance(value, str):
        out = set()
        for part in value.replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.add(int(part))
            except Exception:
                pass
        return out

    try:
        return {int(value)}
    except Exception:
        return set()


_ADMIN_SET = _parse_admin_ids(ADMIN_IDS)


def _is_admin(user_id: int) -> bool:
    return int(user_id) in _ADMIN_SET


def admin_delete_menu_kb() -> ReplyKeyboardMarkup:
    # Возвращаемся в админ-панель (не в главное меню)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔧 Админ")],
            [KeyboardButton(text="⬅️ Назад в меню")],
        ],
        resize_keyboard=True,
    )


async def _fetch_events_for_admin(limit: int = 30) -> list[dict]:
    """
    Забираем события для админа прямо из БД (без зависимости от Repo),
    чтобы не ломаться от DI и несовпадений интерфейсов.
    """
    db = get_db()
    cur = await db.execute(
        """
        SELECT
            id,
            title,
            status,
            COALESCE(event_date, start_date, '') AS any_date
        FROM events
        ORDER BY id DESC
        LIMIT ?
        """,
        (int(limit),),
    )
    rows = await cur.fetchall()

    result: list[dict] = []
    for r in rows:
        # r может быть sqlite3.Row, поддерживает доступ по индексу/имени
        result.append(
            {
                "id": int(r["id"]) if "id" in r.keys() else int(r[0]),
                "title": str(r["title"]) if "title" in r.keys() else str(r[1]),
                "status": str(r["status"]) if "status" in r.keys() else str(r[2]),
                "any_date": str(r["any_date"]) if "any_date" in r.keys() else str(r[3]),
            }
        )
    return result


async def _delete_event_cascade(event_id: int) -> None:
    """
    Удаляем событие и хвосты.
    Если каких-то таблиц нет — просто пропускаем.
    """
    db = get_db()

    # Важно: чистим зависимости вручную, чтобы не зависеть от foreign_keys/cascade
    # и не ломать существующую схему.
    try:
        await db.execute("DELETE FROM event_photos WHERE event_id = ?", (event_id,))
    except Exception:
        pass

    try:
        await db.execute("DELETE FROM promo_orders WHERE event_id = ?", (event_id,))
    except Exception:
        pass

    # Само событие
    await db.execute("DELETE FROM events WHERE id = ?", (event_id,))
    await db.commit()


@router.message(F.text == "🗑 Удалить событие")
async def admin_delete_entry(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ У тебя нет прав администратора.")
        return

    events = await _fetch_events_for_admin(limit=30)
    if not events:
        await message.answer("Событий пока нет.", reply_markup=admin_delete_menu_kb())
        return

    lines = ["🗑 <b>Удаление события</b>\n", "Вот текущие события (последние 30):"]
    for e in events:
        date_txt = e["any_date"] if e["any_date"] else "—"
        lines.append(f"ID {e['id']} | {e['status']} | {date_txt} | {e['title']}")

    lines.append("\n✍️ Отправь мне <b>ID</b> события, которое нужно удалить.")
    await message.answer("\n".join(lines), reply_markup=admin_delete_menu_kb())

    await state.set_state(AdminDelete.waiting_event_id)


@router.message(AdminDelete.waiting_event_id)
async def admin_delete_got_id(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ У тебя нет прав администратора.")
        await state.clear()
        return

    text = (message.text or "").strip()
    try:
        event_id = int(text)
    except ValueError:
        await message.answer("❌ Нужно число. Отправь ID события (например: 12).")
        return

    # проверим, что событие существует
    db = get_db()
    cur = await db.execute("SELECT id, title FROM events WHERE id = ?", (event_id,))
    row = await cur.fetchone()
    if not row:
        await message.answer("❌ Событие с таким ID не найдено. Проверь список и попробуй снова.")
        return

    await _delete_event_cascade(event_id)

    title = row["title"] if hasattr(row, "keys") and "title" in row.keys() else str(row[1])
    await message.answer(f"✅ Событие ID {event_id} удалено: <b>{title}</b>", reply_markup=admin_delete_menu_kb())
    await state.clear()