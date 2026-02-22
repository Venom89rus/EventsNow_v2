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


# ===== UI =====
def organizer_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить мероприятие")],
            [KeyboardButton(text="📈 Продвижение")],
            [KeyboardButton(text="⬅️ Назад в меню")],
        ],
        resize_keyboard=True,
    )


def promo_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 Продвигать мероприятие")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )


def services_kb(event_id: int) -> InlineKeyboardMarkup:
    # цены пока фикс — потом привяжем к Юкассе
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Топ на 24ч — 199₽", callback_data=f"promo_srv:top:{event_id}")],
            [InlineKeyboardButton(text="📣 Оповещение всем — 299₽", callback_data=f"promo_srv:notify:{event_id}")],
            [InlineKeyboardButton(text="✨ Подсветка — 149₽", callback_data=f"promo_srv:highlight:{event_id}")],
            [InlineKeyboardButton(text="⬆️ Поднять (bump) — 99₽", callback_data=f"promo_srv:bump:{event_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="promo_back")],
        ]
    )


def pay_kb(order_id: int) -> InlineKeyboardMarkup:
    # Заглушка оплаты: “✅ Я оплатил”
    # Когда подключим Юкассу — заменим на invoice_url или кнопку оплаты.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"promo_paid:{order_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"promo_cancel:{order_id}")],
        ]
    )


def pick_events_kb(events) -> InlineKeyboardMarkup:
    rows = []
    for e in events:
        rows.append([InlineKeyboardButton(text=f"🆔 {e.id} · {e.title}", callback_data=f"promo_pick:{e.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="promo_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ===== FSM =====
class PromoFSM(StatesGroup):
    wait_event_id = State()


# ===== handlers =====
@router.message(F.text == "📈 Продвижение")
async def promo_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "📈 <b>Продвижение</b>\n\n"
        "Выбирай:\n"
        "⭐ Топ\n"
        "📣 Оповещение\n"
        "✨ Подсветка\n"
        "⬆️ Поднятие\n\n"
        "Нажми кнопку 👇",
        reply_markup=promo_menu_kb(),
    )


@router.message(F.text == "⬅️ Назад")
async def promo_back_to_org(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🎪 Кабинет организатора", reply_markup=organizer_menu_kb())


@router.message(F.text == "🚀 Продвигать мероприятие")
async def promo_choose_event(message: Message, state: FSMContext) -> None:
    await state.clear()
    events = await repo.get_organizer_events(message.from_user.id, limit=10, status="approved")
    if events:
        await message.answer(
            "Выбери своё <b>одобренное</b> событие 👇\n"
            "или отправь ID текстом.",
            reply_markup=pick_events_kb(events),
        )
    else:
        await message.answer(
            "У тебя пока нет одобренных событий.\n\n"
            "Если точно есть — отправь ID события.",
        )
    await state.set_state(PromoFSM.wait_event_id)


@router.callback_query(F.data == "promo_back")
async def promo_cb_back(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.answer("📈 Продвижение", reply_markup=promo_menu_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("promo_pick:"))
async def promo_cb_pick(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    event_id = int(cb.data.split(":")[1])
    await cb.message.answer(
        f"Выбрано событие <b>{event_id}</b>.\n\nВыбери услугу 👇",
        reply_markup=services_kb(event_id),
    )
    await cb.answer()


@router.message(PromoFSM.wait_event_id)
async def promo_wait_id(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Введите числовой ID (например 12).")
        return

    event_id = int(text)
    await state.clear()
    await message.answer(
        f"Выбрано событие <b>{event_id}</b>.\n\nВыбери услугу 👇",
        reply_markup=services_kb(event_id),
    )


@router.callback_query(F.data.startswith("promo_srv:"))
async def promo_cb_service(cb: CallbackQuery) -> None:
    _, service, event_id_str = cb.data.split(":")
    event_id = int(event_id_str)

    # проверка: событие твоё и approved
    ev = await repo.get_event(event_id)
    if not ev:
        await cb.answer("Событие не найдено", show_alert=True)
        return
    if int(ev.organizer_id) != int(cb.from_user.id):
        await cb.answer("Это не твоё событие", show_alert=True)
        return
    if ev.status != "approved":
        await cb.answer("Продвигать можно только approved", show_alert=True)
        return

    prices = {"top": 199, "notify": 299, "highlight": 149, "bump": 99}
    amount = prices.get(service, 0)
    if amount <= 0:
        await cb.answer("Неизвестная услуга", show_alert=True)
        return

    order_id = await repo.create_promo_order(
        organizer_id=cb.from_user.id,
        event_id=event_id,
        service=service,
        amount_rub=amount,
    )

    await cb.message.answer(
        "💳 <b>Оплата</b>\n\n"
        f"Услуга: <b>{service}</b>\n"
        f"Событие: <b>{event_id}</b>\n"
        f"Сумма: <b>{amount}₽</b>\n\n"
        "Сейчас оплата в виде тестовой кнопки.\n"
        "Когда подключим Юкассу — тут будет настоящая ссылка/кнопка оплаты.",
        reply_markup=pay_kb(order_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("promo_paid:"))
async def promo_cb_paid(cb: CallbackQuery) -> None:
    order_id = int(cb.data.split(":")[1])
    order = await repo.get_order(order_id)
    if not order:
        await cb.answer("Заказ не найден", show_alert=True)
        return
    if int(order["organizer_id"]) != int(cb.from_user.id):
        await cb.answer("Это не твой заказ", show_alert=True)
        return

    ok = await repo.mark_order_paid(order_id)
    if not ok:
        await cb.answer("Уже обработано", show_alert=True)
        return

    await repo.set_event_promoted(int(order["event_id"]), kind=str(order["service"]))

    await cb.message.answer(
        "✅ Оплата подтверждена (тест).\n\n"
        "Услуга применена. 🚀\n"
        "Хочешь ещё продвинуть — жми кнопку ниже.",
        reply_markup=promo_menu_kb(),
    )
    await cb.answer("OK")


@router.callback_query(F.data.startswith("promo_cancel:"))
async def promo_cb_cancel(cb: CallbackQuery) -> None:
    await cb.message.answer("❌ Отменено.", reply_markup=promo_menu_kb())
    await cb.answer()