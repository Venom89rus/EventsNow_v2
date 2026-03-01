from __future__ import annotations

import os
from typing import Any, Iterable, Optional

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.enums import ParseMode

from bot.db.repositories import repo

from typing import Any, Optional


router = Router()

def _val(obj, key: str, default: str = ""):
    """Безопасно достаёт поле из dict/dataclass/ORM-объекта (Event и т.п.)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# =========================
# ADMIN IDS
# =========================
def _load_admin_ids() -> set[int]:
    # ENV: ADMIN_IDS="123,456"
    raw = (os.getenv("ADMIN_IDS") or "").strip()
    if not raw:
        return set()
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


ADMIN_IDS = _load_admin_ids()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# =========================
# UI
# =========================
def admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏳ На модерации")],
            [KeyboardButton(text="🗑 Удалить событие")],
            [KeyboardButton(text="⬅️ Назад в меню")],
        ],
        resize_keyboard=True,
    )


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏠 Житель")],
            [KeyboardButton(text="🎪 Организатор")],
            [KeyboardButton(text="📞 Обратная связь")],
            [KeyboardButton(text="🔧 Админ")],
        ],
        resize_keyboard=True,
    )


def pending_list_kb(events: Iterable[Any]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for e in events:
        eid = int(getattr(e, "id"))
        title = str(getattr(e, "title", "") or "")
        label = f"🆔 {eid} · {title}"
        if len(label) > 45:
            label = label[:45].rstrip() + "…"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"adm_show:{eid}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm_back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def moderation_kb(event_id: int, has_more: bool, next_id: Optional[int]) -> InlineKeyboardMarkup:
    row1 = [
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"adm_ok:{event_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_no:{event_id}"),
    ]
    row2: list[InlineKeyboardButton] = []
    if has_more:
        row2.append(InlineKeyboardButton(text="📄 Подробнее", callback_data=f"adm_more:{event_id}"))
    row2.append(InlineKeyboardButton(text="⬅️ К списку", callback_data="adm_list"))

    inline_keyboard = [row1, row2]
    if next_id is not None:
        inline_keyboard.append([InlineKeyboardButton(text="➡️ Следующее", callback_data=f"adm_show:{next_id}")])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


# =========================
# HELPERS
# =========================
def _safe(v: Any, fallback: str = "—") -> str:
    if v is None:
        return fallback
    s = str(v).strip()
    return s if s else fallback


def short_desc(text: str, limit: int = 100) -> tuple[str, bool]:
    if not text:
        return "—", False
    s = text.strip()
    if len(s) <= limit:
        return s, False
    return s[:limit].rstrip() + "…", True

# --- ДОБАВЬ где-нибудь рядом с _safe()/short_desc(), например перед build_admin_caption ---


def _ev(event: Any, key: str, default=None):
    """Безопасно достаёт поле из dict или объекта."""
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default)

def build_admin_caption(event: Any) -> tuple[str, bool]:
    eid = int(_ev(event, "id"))
    cat = _safe(_ev(event, "category"))
    title = _safe(_ev(event, "title"))
    location = _safe(_ev(event, "location"))
    price = _safe(_ev(event, "price_text"))
    ticket_link = _safe(_ev(event, "ticket_link"))
    phone = _safe(_ev(event, "phone"))
    organizer_id = _safe(_ev(event, "organizer_id"))
    fmt = _safe(_ev(event, "event_format"), "single")

    # даты/время по формату
    if fmt == "period":
        date_text = f"{_safe(_ev(event, 'start_date'))} — {_safe(_ev(event, 'end_date'))}"
        time_text = f"{_safe(_ev(event, 'open_time'))} — {_safe(_ev(event, 'close_time'))}"
    elif fmt == "sessions":
        date_text = f"{_safe(_ev(event, 'sessions_start_date'))} — {_safe(_ev(event, 'sessions_end_date'))}"
        time_text = _safe(_ev(event, "sessions_times"))
    else:
        date_text = _safe(
            _ev(event, "event_date") or
            _ev(event, "start_date")
        )
        time_text = _safe(
            _ev(event, "event_time") or
            _ev(event, "start_time") or
            _ev(event, "open_time")
        )

    desc_full = _safe(_ev(event, "description"), "")
    desc_short, cut = short_desc(desc_full, 100)

    caption = "\n".join([
        "🛡 <b>Модерация события</b>",
        "",
        f"🆔 <b>{eid}</b>",
        f"{cat}",
        f"<b>{title}</b>",
        "",
        f"📝 {desc_short}",
        "",
        f"📅 {date_text}",
        f"⏰ {time_text}",
        f"📍 {location}",
        f"💰 {price}",
        f"🔗 {ticket_link}",
        f"📞 {phone}",
        f"👤 organizer_id: {organizer_id}",
    ])
    return caption, cut

async def _get_next_pending_id(current_id: int) -> Optional[int]:
    pending = await repo.get_pending_events(limit=50)
    ids = [int(_ev(e, "id")) for e in pending]
    if not ids:
        return None
    if current_id not in ids:
        return ids[0]
    i = ids.index(current_id)
    return ids[i + 1] if i + 1 < len(ids) else None

async def send_event_for_moderation(
    target: Message | CallbackQuery,
    event: Any,
    next_id: Optional[int],
) -> None:
    caption, cut = build_admin_caption(event)
    eid = int(_ev(event, "id"))

    photos = await repo.get_event_photos(eid)
    photo_id = photos[0] if photos else None

    kb = moderation_kb(event_id=eid, has_more=cut, next_id=next_id)

    if isinstance(target, CallbackQuery):
        if photo_id:
            await target.message.answer_photo(photo=photo_id, caption=caption, reply_markup=kb)
        else:
            await target.message.answer(caption, reply_markup=kb)
        await target.answer()
    else:
        if photo_id:
            await target.answer_photo(photo=photo_id, caption=caption, reply_markup=kb)
        else:
            await target.answer(caption, reply_markup=kb)


# =========================
# ENTRY
# =========================
@router.message(F.text == "🔧 Админ")
async def admin_entry(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    await message.answer(
        "🔧 <b>Админ-панель</b>\n\n"
        "Здесь ты можешь:\n"
        "✅ Модерировать события\n\n"
        "Выбирай пункт меню 👇",
        reply_markup=admin_menu_kb(),
    )


@router.message(F.text == "⬅️ Назад в меню")
async def admin_back_to_main(message: Message) -> None:
    await message.answer("🏠 Главное меню", reply_markup=main_menu_kb())


# =========================
# LIST
# =========================
@router.message(F.text == "⏳ На модерации")
async def admin_pending(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    pending = await repo.get_pending_events(limit=30)
    if not pending:
        await message.answer("✅ Сейчас нет событий на модерации.")
        return

    await message.answer(
        "⏳ <b>Список событий на модерации</b>\nВыбери событие 👇",
        reply_markup=pending_list_kb(pending),
    )


@router.callback_query(F.data == "adm_list")
async def admin_cb_list(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return

    pending = await repo.get_pending_events(limit=30)
    if not pending:
        await cb.message.answer("✅ Сейчас нет событий на модерации.")
        await cb.answer()
        return

    await cb.message.answer(
        "⏳ <b>Список событий на модерации</b>\nВыбери событие 👇",
        reply_markup=pending_list_kb(pending),
    )
    await cb.answer()


@router.callback_query(F.data == "adm_back_menu")
async def admin_cb_back_menu(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return
    await cb.message.answer("🔧 Админ-панель", reply_markup=admin_menu_kb())
    await cb.answer()


# =========================
# SHOW
# =========================
@router.callback_query(F.data.startswith("adm_show:"))
async def admin_cb_show(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return

    event_id = int(cb.data.split(":")[1])
    event = await repo.get_event(event_id)
    if not event:
        await cb.answer("Событие не найдено", show_alert=True)
        return

    next_id = await _get_next_pending_id(event_id)
    await send_event_for_moderation(cb, event, next_id=next_id)


# =========================
# ACTIONS
# =========================
@router.callback_query(F.data.startswith("adm_ok:"))
async def admin_cb_approve(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return

    event_id = int(cb.data.split(":")[1])
    ok = await repo.approve_event(event_id, admin_id=cb.from_user.id)

    if not ok:
        await cb.answer("Не удалось одобрить", show_alert=True)
        return

    await cb.message.answer(f"✅ Событие <b>{event_id}</b> одобрено.")
    next_id = await _get_next_pending_id(event_id)
    if next_id is not None:
        ev = await repo.get_event(next_id)
        if ev:
            await send_event_for_moderation(cb, ev, next_id=await _get_next_pending_id(next_id))

    await cb.answer("Одобрено")


@router.callback_query(F.data.startswith("adm_no:"))
async def admin_cb_reject(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return

    event_id = int(cb.data.split(":")[1])
    ok = await repo.reject_event(event_id, admin_id=cb.from_user.id)

    if not ok:
        await cb.answer("Не удалось отклонить", show_alert=True)
        return

    await cb.message.answer(f"❌ Событие <b>{event_id}</b> отклонено.")
    next_id = await _get_next_pending_id(event_id)
    if next_id is not None:
        ev = await repo.get_event(next_id)
        if ev:
            await send_event_for_moderation(cb, ev, next_id=await _get_next_pending_id(next_id))

    await cb.answer("Отклонено")


# =========================
# MORE
# =========================
@router.callback_query(F.data.startswith("adm_more:"))
async def admin_cb_more(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return

    event_id = int(cb.data.split(":")[1])
    event = await repo.get_event(event_id)
    if not event:
        await cb.answer("Событие не найдено", show_alert=True)
        return

    full = (event.description or "").strip()
    if not full:
        await cb.answer("Описание пустое", show_alert=True)
        return

    await cb.message.answer(f"📄 <b>Полное описание (ID {event_id})</b>\n\n{full}")
    await cb.answer()