from __future__ import annotations

from typing import Any

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.db.repositories import repo

router = Router()

# =========================
# UI
# =========================
def organizer_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить мероприятие")],
            [KeyboardButton(text="⬅️ Назад в меню")],
        ],
        resize_keyboard=True,
    )


def categories_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎵 Концерт")],
            [KeyboardButton(text="🎭 Спектакль")],
            [KeyboardButton(text="🧑‍🎓 Мастер-класс")],
            [KeyboardButton(text="🖼 Выставка")],
            [KeyboardButton(text="🎤 Лекция")],
            [KeyboardButton(text="📌 Другое")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )


def format_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Разовое событие")],
            [KeyboardButton(text="🗓 Период")],
            [KeyboardButton(text="🎟 Сеансы")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )


def back_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)


def photos_done_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Готово")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )


def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data="org_confirm"),
                InlineKeyboardButton(text="❌ Отменить", callback_data="org_cancel"),
            ]
        ]
    )


# =========================
# FSM
# =========================
class AddEvent(StatesGroup):
    category = State()
    title = State()
    description = State()
    event_format = State()

    date_single = State()
    time_single = State()

    date_from = State()
    date_to = State()
    time_from = State()
    time_to = State()

    location = State()
    price = State()
    ticket_link = State()
    phone = State()

    photos = State()


# =========================
# HELPERS
# =========================
def _safe(v: Any, fallback: str = "—") -> str:
    if v is None:
        return fallback
    s = str(v).strip()
    return s if s else fallback


def _format_preview(data: dict[str, Any]) -> str:
    cat = _safe(data.get("category"))
    title = _safe(data.get("title"))
    desc = _safe(data.get("description"), "")

    fmt = _safe(data.get("event_format"))

    if fmt == "single":
        date_text = _safe(data.get("event_date"))
        time_text = _safe(data.get("event_time"))
    elif fmt == "period":
        date_text = f"{_safe(data.get('date_from'))} — {_safe(data.get('date_to'))}"
        time_text = f"{_safe(data.get('time_from'))} — {_safe(data.get('time_to'))}"
    else:
        date_text = _safe(data.get("event_date"))
        time_text = _safe(data.get("event_time"))

    location = _safe(data.get("location"))
    price = _safe(data.get("price"))
    ticket_link = _safe(data.get("ticket_link"))
    phone = _safe(data.get("phone"))

    photos = data.get("photos") or []
    photos_line = f"🖼 Фото: {len(photos)}/5" if photos else "🖼 Фото: 0/5"

    parts = [
        "📋 <b>Предпросмотр мероприятия</b>",
        "",
        f"{cat}",
        f"<b>{title}</b>",
        "",
    ]
    if desc and desc != "—":
        parts.append(desc)
        parts.append("")

    parts += [
        f"📅 {date_text}  ⏰ {time_text}",
        f"📍 {location}",
        f"💰 {price}",
        f"🔗 {ticket_link}",
        f"📞 {phone}",
        photos_line,
    ]
    return "\n".join(parts)


async def _send_rest_photos(message: Message, photos: list[str]) -> None:
    if len(photos) <= 1:
        return
    media = [InputMediaPhoto(media=fid) for fid in photos[1:5]]
    await message.answer_media_group(media)


# =========================
# ORGANIZER ENTRY
# =========================
@router.message(F.text == "🎪 Организатор")
async def organizer_entry(message: Message) -> None:
    await message.answer(
        "🎪 <b>Кабинет организатора</b>\n\n"
        "Здесь ты можешь:\n"
        "➕ Добавлять мероприятия\n"
        "📈 Продвигать их\n"
        "🛠 Управлять событиями\n\n"
        "Начнём?",
        reply_markup=organizer_menu_kb(),
    )


@router.message(F.text == "⬅️ Назад в меню")
async def org_back_to_main(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Ок 👍 Возвращаю в главное меню. Нажми /start")


# =========================
# ADD FLOW
# =========================
@router.message(F.text == "➕ Добавить мероприятие")
async def add_event_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddEvent.category)
    await message.answer("Выбери категорию мероприятия 👇", reply_markup=categories_kb())


@router.message(AddEvent.category, F.text == "⬅️ Назад")
async def add_event_back_from_category(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🎪 Кабинет организатора", reply_markup=organizer_menu_kb())


@router.message(AddEvent.category)
async def add_event_category(message: Message, state: FSMContext) -> None:
    await state.update_data(category=message.text.strip())
    await state.set_state(AddEvent.title)
    await message.answer("✏️ Введи название мероприятия\nНапример: Группа «Мираж»", reply_markup=back_kb())


@router.message(AddEvent.title)
async def add_event_title(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "⬅️ Назад":
        await state.set_state(AddEvent.category)
        await message.answer("Выбери категорию мероприятия 👇", reply_markup=categories_kb())
        return
    await state.update_data(title=message.text.strip())
    await state.set_state(AddEvent.description)
    await message.answer("📝 Теперь опиши мероприятие\nКратко и по делу — это важно для посетителей.", reply_markup=back_kb())


@router.message(AddEvent.description)
async def add_event_description(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "⬅️ Назад":
        await state.set_state(AddEvent.title)
        await message.answer("✏️ Введи название мероприятия", reply_markup=back_kb())
        return
    await state.update_data(description=message.text.strip())
    await state.set_state(AddEvent.event_format)
    await message.answer("📌 Выбери формат события", reply_markup=format_kb())


@router.message(AddEvent.event_format, F.text == "📅 Разовое событие")
async def add_event_format_single(message: Message, state: FSMContext) -> None:
    await state.update_data(event_format="single")
    await state.set_state(AddEvent.date_single)
    await message.answer("📅 Введи дату мероприятия\nФормат: 31.12.2025", reply_markup=back_kb())


@router.message(AddEvent.event_format, F.text == "🗓 Период")
async def add_event_format_period(message: Message, state: FSMContext) -> None:
    await state.update_data(event_format="period")
    await state.set_state(AddEvent.date_from)
    await message.answer("📅 Введи дату НАЧАЛА\nФормат: 31.12.2025", reply_markup=back_kb())


@router.message(AddEvent.event_format, F.text == "🎟 Сеансы")
async def add_event_format_sessions(message: Message, state: FSMContext) -> None:
    await state.update_data(event_format="sessions")
    await state.set_state(AddEvent.date_single)
    await message.answer("📅 Введи дату мероприятия\nФормат: 31.12.2025", reply_markup=back_kb())


@router.message(AddEvent.event_format, F.text == "⬅️ Назад")
async def add_event_format_back(message: Message, state: FSMContext) -> None:
    await state.set_state(AddEvent.description)
    await message.answer("📝 Теперь опиши мероприятие", reply_markup=back_kb())


@router.message(AddEvent.date_single)
async def add_event_date_single(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "⬅️ Назад":
        await state.set_state(AddEvent.event_format)
        await message.answer("📌 Выбери формат события", reply_markup=format_kb())
        return
    await state.update_data(event_date=message.text.strip())
    await state.set_state(AddEvent.time_single)
    await message.answer("⏰ Введи время начала\nФормат: 19:00", reply_markup=back_kb())


@router.message(AddEvent.time_single)
async def add_event_time_single(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "⬅️ Назад":
        await state.set_state(AddEvent.date_single)
        await message.answer("📅 Введи дату мероприятия\nФормат: 31.12.2025", reply_markup=back_kb())
        return
    await state.update_data(event_time=message.text.strip())
    await state.set_state(AddEvent.location)
    await message.answer("📍 Укажи место проведения\nАдрес или название площадки", reply_markup=back_kb())


@router.message(AddEvent.date_from)
async def add_event_date_from(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "⬅️ Назад":
        await state.set_state(AddEvent.event_format)
        await message.answer("📌 Выбери формат события", reply_markup=format_kb())
        return
    await state.update_data(date_from=message.text.strip())
    await state.set_state(AddEvent.date_to)
    await message.answer("📅 Введи дату ОКОНЧАНИЯ\nФормат: 31.12.2025", reply_markup=back_kb())


@router.message(AddEvent.date_to)
async def add_event_date_to(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "⬅️ Назад":
        await state.set_state(AddEvent.date_from)
        await message.answer("📅 Введи дату НАЧАЛА\nФормат: 31.12.2025", reply_markup=back_kb())
        return
    await state.update_data(date_to=message.text.strip())
    await state.set_state(AddEvent.time_from)
    await message.answer("⏰ Введи время НАЧАЛА (например 10:00)", reply_markup=back_kb())


@router.message(AddEvent.time_from)
async def add_event_time_from(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "⬅️ Назад":
        await state.set_state(AddEvent.date_to)
        await message.answer("📅 Введи дату ОКОНЧАНИЯ\nФормат: 31.12.2025", reply_markup=back_kb())
        return
    await state.update_data(time_from=message.text.strip())
    await state.set_state(AddEvent.time_to)
    await message.answer("⏰ Введи время ОКОНЧАНИЯ (например 18:00)", reply_markup=back_kb())


@router.message(AddEvent.time_to)
async def add_event_time_to(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "⬅️ Назад":
        await state.set_state(AddEvent.time_from)
        await message.answer("⏰ Введи время НАЧАЛА (например 10:00)", reply_markup=back_kb())
        return
    await state.update_data(time_to=message.text.strip())
    await state.set_state(AddEvent.location)
    await message.answer("📍 Укажи место проведения\nАдрес или название площадки", reply_markup=back_kb())


@router.message(AddEvent.location)
async def add_event_location(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "⬅️ Назад":
        data = await state.get_data()
        fmt = data.get("event_format")
        if fmt == "period":
            await state.set_state(AddEvent.time_to)
            await message.answer("⏰ Введи время ОКОНЧАНИЯ (например 18:00)", reply_markup=back_kb())
        else:
            await state.set_state(AddEvent.time_single)
            await message.answer("⏰ Введи время начала\nФормат: 19:00", reply_markup=back_kb())
        return

    await state.update_data(location=message.text.strip())
    await state.set_state(AddEvent.price)
    await message.answer(
        "💰 Укажи стоимость билетов\nПримеры:\n• Бесплатно\n• 300 ₽\n• от 300 до 1000 ₽",
        reply_markup=back_kb(),
    )


@router.message(AddEvent.price)
async def add_event_price(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "⬅️ Назад":
        await state.set_state(AddEvent.location)
        await message.answer("📍 Укажи место проведения", reply_markup=back_kb())
        return
    await state.update_data(price=message.text.strip())
    await state.set_state(AddEvent.ticket_link)
    await message.answer("🔗 Вставь ссылку на покупку билетов\n(если нет — напиши «Нет»)", reply_markup=back_kb())


@router.message(AddEvent.ticket_link)
async def add_event_ticket_link(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "⬅️ Назад":
        await state.set_state(AddEvent.price)
        await message.answer("💰 Укажи стоимость билетов", reply_markup=back_kb())
        return
    await state.update_data(ticket_link=message.text.strip())
    await state.set_state(AddEvent.phone)
    await message.answer("📞 Контактный телефон для связи\nФормат: +7XXXXXXXXXX", reply_markup=back_kb())


@router.message(AddEvent.phone)
async def add_event_phone(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "⬅️ Назад":
        await state.set_state(AddEvent.ticket_link)
        await message.answer("🔗 Вставь ссылку на покупку билетов", reply_markup=back_kb())
        return
    await state.update_data(phone=message.text.strip(), photos=[])
    await state.set_state(AddEvent.photos)
    await message.answer("🖼 Отправь до 5 фото (афиша). Когда закончишь — нажми ✅ Готово", reply_markup=photos_done_kb())


@router.message(AddEvent.photos, F.text == "⬅️ Назад")
async def add_event_photos_back(message: Message, state: FSMContext) -> None:
    await state.set_state(AddEvent.phone)
    await message.answer("📞 Контактный телефон для связи", reply_markup=back_kb())


@router.message(AddEvent.photos, F.photo)
async def add_event_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photos: list[str] = data.get("photos") or []
    if len(photos) >= 5:
        await message.answer("⚠️ Можно максимум 5 фото. Нажми ✅ Готово.")
        return

    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer(f"✅ Фото добавлено ({len(photos)}/5). Ещё отправляй или жми ✅ Готово.")


@router.message(AddEvent.photos, F.text == "✅ Готово")
async def add_event_done_photos(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photos: list[str] = data.get("photos") or []
    preview = _format_preview(data)

    # ✅ КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ ДУБЛЯ:
    # если есть фото — карточка = первое фото + caption(все поля) + кнопки
    if photos:
        await message.answer_photo(photo=photos[0], caption=preview, reply_markup=confirm_kb())
        await _send_rest_photos(message, photos)
    else:
        await message.answer(preview, reply_markup=confirm_kb())


@router.callback_query(F.data == "org_cancel")
async def org_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.answer("❌ Отменено. Возвращаю в кабинет организатора.", reply_markup=organizer_menu_kb())
    await cb.answer()


@router.callback_query(F.data == "org_confirm")
async def org_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()

    organizer_id = cb.from_user.id
    await repo.ensure_user(organizer_id)

    fmt = data.get("event_format") or "single"

    if fmt == "period":
        start_date = _safe(data.get("date_from"), "")
        end_date = _safe(data.get("date_to"), "")
        start_time = _safe(data.get("time_from"), "")
        end_time = _safe(data.get("time_to"), "")
    else:
        start_date = _safe(data.get("event_date"), "")
        end_date = start_date
        start_time = _safe(data.get("event_time"), "")
        end_time = start_time

    await repo.create_event(
        organizer_id=organizer_id,
        category=_safe(data.get("category"), ""),
        title=_safe(data.get("title"), ""),
        description=_safe(data.get("description"), ""),
        event_format=_safe(fmt, "single"),
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        location=_safe(data.get("location"), ""),
        price_text=_safe(data.get("price"), ""),
        ticket_link=_safe(data.get("ticket_link"), ""),
        phone=_safe(data.get("phone"), ""),
        photo_ids=(data.get("photos") or []),
        status="pending",
    )

    await state.clear()

    # ✅ после отправки — возвращаем кнопки организатора
    await cb.message.answer(
        "✅ Мероприятие отправлено на модерацию!\n\nПосле проверки оно появится в боте 🚀",
        reply_markup=organizer_menu_kb(),
    )
    await cb.answer()