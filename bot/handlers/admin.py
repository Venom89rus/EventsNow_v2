from __future__ import annotations

from typing import Iterable, Optional

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from bot.db.repositories import repo, Event

try:
    from bot.config import ADMIN_IDS  # type: ignore
except Exception:
    ADMIN_IDS = []

router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in set(int(x) for x in (ADMIN_IDS or []))


def admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏳ На модерации")],
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


def pending_list_kb(events: Iterable[Event]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for e in events:
        label = f"🆔 {e.id} · {e.title}"
        if len(label) > 45:
            label = label[:45].rstrip() + "…"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"adm_show:{e.id}")])
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

    kb: list[list[InlineKeyboardButton]] = [row1, row2]
    if next_id is not None:
        kb.append([InlineKeyboardButton(text="➡️ Следующее", callback_data=f"adm_show:{next_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def short_desc(text: str, limit: int = 100) -> tuple[str, bool]:
    s = (text or "").strip()
    if not s:
        return "—", False
    if len(s) <= limit:
        return s, False
    return s[:limit].rstrip() + "…", True


def build_admin_caption(event: Event) -> tuple[str, bool]:
    desc_short, cut = short_desc(event.description, 100)

    if event.event_format == "period":
        date_text = f"{event.start_date} — {event.end_date}"
        time_text = f"{event.start_time} — {event.end_time}"
    else:
        date_text = event.start_date
        time_text = event.start_time

    parts = [
        "🛡 <b>Модерация события</b>",
        "",
        f"🆔 <b>{event.id}</b>",
        f"{event.category}",
        f"<b>{event.title}</b>",
        "",
        f"📝 {desc_short}",
        "",
        f"📅 {date_text}",
        f"⏰ {time_text}",
        f"📍 {event.location or '—'}",
        f"💰 {event.price_text or '—'}",
        f"🔗 {event.ticket_link or '—'}",
        f"📞 {event.phone or '—'}",
        f"👤 organizer_id: {event.organizer_id}",
    ]
    return "\n".join(parts), cut


async def _get_next_pending_id(current_id: int) -> Optional[int]:
    pending = await repo.get_pending_events(limit=50)
    ids = [e.id for e in pending]
    if not ids:
        return None
    if current_id not in ids:
        return ids[0]
    idx = ids.index(current_id)
    return ids[idx + 1] if idx + 1 < len(ids) else None


async def send_event_for_moderation(target: Message | CallbackQuery, event: Event, next_id: Optional[int]) -> None:
    caption, cut = build_admin_caption(event)
    kb = moderation_kb(event_id=event.id, has_more=cut, next_id=next_id)
    photo_id = event.photo_ids[0] if event.photo_ids else None

    if isinstance(target, CallbackQuery):
        msg = target.message
        if photo_id:
            await msg.answer_photo(photo=photo_id, caption=caption, reply_markup=kb)
        else:
            await msg.answer(caption, reply_markup=kb)
        await target.answer()
    else:
        if photo_id:
            await target.answer_photo(photo=photo_id, caption=caption, reply_markup=kb)
        else:
            await target.answer(caption, reply_markup=kb)


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
        nxt = await repo.get_event(next_id)
        if nxt:
            await send_event_for_moderation(cb, nxt, next_id=await _get_next_pending_id(next_id))
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
        nxt = await repo.get_event(next_id)
        if nxt:
            await send_event_for_moderation(cb, nxt, next_id=await _get_next_pending_id(next_id))
    await cb.answer("Отклонено")


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