from __future__ import annotations

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from bot.db.repositories import repo

router = Router()


def promo_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 Поднять мероприятие")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )


def organizer_menu_kb() -> ReplyKeyboardMarkup:
    # повторяем твою клаву, чтобы не импортировать и не ловить циклы
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить мероприятие")],
            [KeyboardButton(text="📈 Продвижение")],
            [KeyboardButton(text="⬅️ Назад в меню")],
        ],
        resize_keyboard=True,
    )


class PromoFSM(StatesGroup):
    wait_event_id = State()


def events_pick_kb(events) -> InlineKeyboardMarkup:
    rows = []
    for e in events:
        rows.append([InlineKeyboardButton(text=f"🆔 {e.id} · {e.title}", callback_data=f"promo_pick:{e.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="promo_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "📈 Продвижение")
async def promo_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "📈 <b>Продвижение</b>\n\n"
        "Здесь ты можешь поднять <b>свои</b> одобренные мероприятия.\n"
        "Нажми кнопку ниже 👇",
        reply_markup=promo_menu_kb(),
    )


@router.message(F.text == "⬅️ Назад")
async def promo_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🎪 Кабинет организатора", reply_markup=organizer_menu_kb())


@router.message(F.text == "🚀 Поднять мероприятие")
async def promo_bump_start(message: Message, state: FSMContext) -> None:
    await state.clear()

    # покажем последние одобренные события организатора
    events = await repo.get_organizer_events(message.from_user.id, limit=10, status="approved")

    if events:
        await message.answer(
            "Выбери событие из списка 👇\n"
            "или отправь ID текстом.",
            reply_markup=events_pick_kb(events),
        )
    else:
        await message.answer(
            "У тебя пока нет одобренных событий.\n\n"
            "Отправь ID события, если уверен что оно approved.",
        )

    await state.set_state(PromoFSM.wait_event_id)


@router.callback_query(F.data == "promo_back")
async def promo_cb_back(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.answer("📈 Продвижение", reply_markup=promo_menu_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("promo_pick:"))
async def promo_cb_pick(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PromoFSM.wait_event_id)
    event_id = int(cb.data.split(":")[1])

    ok, reason = await repo.bump_event(event_id, organizer_id=cb.from_user.id)
    if ok:
        await cb.message.answer(f"🚀 Готово! Событие <b>{event_id}</b> поднято.", reply_markup=promo_menu_kb())
    else:
        await cb.message.answer(f"⚠️ Не получилось: {reason}", reply_markup=promo_menu_kb())
    await cb.answer()


@router.message(PromoFSM.wait_event_id)
async def promo_wait_id(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Введите числовой ID события (например 12).")
        return

    event_id = int(text)
    ok, reason = await repo.bump_event(event_id, organizer_id=message.from_user.id)
    if ok:
        await message.answer(f"🚀 Готово! Событие <b>{event_id}</b> поднято.", reply_markup=promo_menu_kb())
    else:
        await message.answer(f"⚠️ Не получилось: {reason}", reply_markup=promo_menu_kb())

    await state.clear()