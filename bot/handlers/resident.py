# bot/handlers/resident.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from aiogram import Router, F
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from bot.db.database import get_db

router = Router()

FEED_LIMIT = 10

# Категории жителя (как договаривались) + ТОП/Рекомендуем отдельным фильтром
RESIDENT_CATEGORIES = ["концерт", "спектакль", "мастер-класс", "выставка", "лекция", "другое"]

DATE_FILTERS = {
    "📅 Сегодня": 1,
    "📅 3 дня": 3,
    "📅 7 дней": 7,
    "📅 30 дней": 30,
}


class ResidentBrowse(StatesGroup):
    choose_date = State()
    choose_category = State()


def resident_menu_kb() -> ReplyKeyboardMarkup:
    # МЕНЮ СНИЗУ (ReplyKeyboardMarkup)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔄 Обновить")],
            [KeyboardButton(text="📅 По дате"), KeyboardButton(text="🎭 По категории")],
            [KeyboardButton(text="🔥 ТОП/Рекомендуем")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )


def date_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 3 дня")],
            [KeyboardButton(text="📅 7 дней"), KeyboardButton(text="📅 30 дней")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )


def categories_kb() -> ReplyKeyboardMarkup:
    # 2 кнопки в ряд
    rows = []
    cats = RESIDENT_CATEGORIES[:]
    for i in range(0, len(cats), 2):
        row = [KeyboardButton(text=f"🎭 {cats[i]}")]
        if i + 1 < len(cats):
            row.append(KeyboardButton(text=f"🎭 {cats[i+1]}"))
        rows.append(row)

    rows.append([KeyboardButton(text="⬅️ Назад")])

    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


@dataclass
class EventCard:
    id: int
    title: str
    category_text: str
    start_date: str | None
    event_date: str | None
    event_time: str | None
    location: str
    price_text: str
    ticket_link: str
    promoted_kind: str
    highlighted: int


def _today_iso() -> str:
    return date.today().isoformat()


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _event_best_date(e: EventCard) -> str | None:
    # приоритет: start_date -> event_date
    return e.start_date or e.event_date


def _is_paid_or_promoted(e: EventCard) -> bool:
    # “платность/продвижение” считаем по колонкам продвижения
    if (e.promoted_kind or "").strip():
        return True
    if int(e.highlighted or 0) == 1:
        return True
    return False


def _is_top_recommended(e: EventCard) -> bool:
    k = (e.promoted_kind or "").strip().lower()
    return k in {"top", "топ", "recommended", "recommend", "рекомендуем"} or int(e.highlighted or 0) == 1


async def _get_first_photo_file_id(event_id: int) -> str | None:
    db = get_db()
    cur = await db.execute(
        "SELECT file_id FROM event_photos WHERE event_id = ? ORDER BY position ASC, id ASC LIMIT 1",
        (event_id,),
    )
    row = await cur.fetchone()
    return row["file_id"] if row else None


async def _fetch_paid_events(
    limit: int = FEED_LIMIT,
    days: int | None = None,
    category: str | None = None,
    only_top: bool = False,
) -> list[EventCard]:
    """
    Достаём события для Жителя:
    - только approved
    - только НЕ прошедшие
    - только продвинутые/оплаченные
    - сортировка по “важности”: TOP/подсветка/бамп вверх, затем по ближайшей дате
    """
    db = get_db()

    today = date.today()
    date_from = today
    date_to = None
    if days is not None:
        date_to = today + timedelta(days=max(days - 1, 0))

    where = ["status = 'approved'"]
    params: list[object] = []

    # исключаем прошедшие:
    # берём лучшую дату: COALESCE(start_date, event_date)
    where.append("date(COALESCE(start_date, event_date)) >= date(?)")
    params.append(date_from.isoformat())

    if date_to is not None:
        where.append("date(COALESCE(start_date, event_date)) <= date(?)")
        params.append(date_to.isoformat())

    if category:
        # category_text у тебя используется для отображения/фильтра
        where.append("(lower(category_text) = lower(?) OR lower(category) = lower(?))")
        params.extend([category, category])

    # только “оплаченные/продвинутые”
    where.append("(trim(COALESCE(promoted_kind,'')) <> '' OR COALESCE(highlighted,0) = 1)")

    if only_top:
        where.append("(lower(trim(COALESCE(promoted_kind,''))) IN ('top','топ','recommended','recommend','рекомендуем') OR COALESCE(highlighted,0)=1)")

    where_sql = " AND ".join(where)

    # Сортировка:
    # 1) TOP/рекомендованные выше
    # 2) подсветка выше
    # 3) bumped_at (если есть) — новее выше
    # 4) ближайшая дата выше
    sql = f"""
    SELECT
        id, title, category_text,
        start_date, event_date, event_time,
        location, price_text, ticket_link,
        promoted_kind, highlighted
    FROM events
    WHERE {where_sql}
    ORDER BY
        CASE
            WHEN lower(trim(COALESCE(promoted_kind,''))) IN ('top','топ','recommended','recommend','рекомендуем') THEN 0
            ELSE 1
        END,
        COALESCE(highlighted,0) DESC,
        COALESCE(bumped_at,'') DESC,
        date(COALESCE(start_date, event_date)) ASC,
        COALESCE(event_time,'') ASC,
        id DESC
    LIMIT ?
    """
    params.append(int(limit))

    cur = await db.execute(sql, tuple(params))
    rows = await cur.fetchall()

    out: list[EventCard] = []
    for r in rows:
        out.append(
            EventCard(
                id=int(r["id"]),
                title=str(r["title"] or ""),
                category_text=str(r["category_text"] or ""),
                start_date=r["start_date"],
                event_date=r["event_date"],
                event_time=r["event_time"],
                location=str(r["location"] or ""),
                price_text=str(r["price_text"] or ""),
                ticket_link=str(r["ticket_link"] or ""),
                promoted_kind=str(r["promoted_kind"] or ""),
                highlighted=int(r["highlighted"] or 0),
            )
        )
    return out


def _format_card_text(e: EventCard) -> str:
    d = _event_best_date(e)
    t = (e.event_time or "").strip()

    when = "📅 <b>Дата:</b> не указана"
    if d:
        when = f"📅 <b>Дата:</b> {d}"
    if d and t:
        when = f"📅 <b>Дата:</b> {d}  ⏰ <b>Время:</b> {t}"
    elif t and not d:
        when = f"⏰ <b>Время:</b> {t}"

    cat = (e.category_text or "").strip()
    cat_line = f"🎭 <b>Категория:</b> {cat}" if cat else ""

    loc_line = f"📍 <b>Место:</b> {e.location}" if e.location else ""
    price_line = f"💳 <b>Цена:</b> {e.price_text}" if e.price_text else ""

    badge = "🔥 <b>Рекомендуем</b>\n" if _is_top_recommended(e) else ""

    lines = [
        badge + f"🧾 <b>{e.title}</b>",
        cat_line,
        when,
        loc_line,
        price_line,
    ]
    lines = [x for x in lines if x]  # убрать пустые
    return "\n".join(lines)


def _ticket_kb(e: EventCard) -> InlineKeyboardMarkup | None:
    link = (e.ticket_link or "").strip()
    if not link:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎟 Купить билет", url=link)]
        ]
    )


async def _send_feed(message: Message, events: list[EventCard]) -> None:
    if not events:
        await message.answer(
            "Пока нет подходящих мероприятий 🙁\n\n"
            "Попробуй изменить фильтр или зайди позже.",
            reply_markup=resident_menu_kb(),
        )
        return

    # меню снизу сохраняем: ставим reply_markup на первом сообщении
    await message.answer(
        "🗓 Показываю мероприятия (до 10 шт.).\n"
        "Фильтры — кнопками снизу 👇",
        reply_markup=resident_menu_kb(),
    )

    for e in events:
        photo_id = await _get_first_photo_file_id(e.id)
        text = _format_card_text(e)
        ikb = _ticket_kb(e)

        if photo_id:
            await message.answer_photo(photo=photo_id, caption=text, reply_markup=ikb)
        else:
            await message.answer(text, reply_markup=ikb)


@router.message(F.text == "🏠 Житель")
async def resident_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    events = await _fetch_paid_events(limit=FEED_LIMIT)
    await _send_feed(message, events)


@router.message(F.text == "🔄 Обновить")
async def resident_refresh(message: Message, state: FSMContext) -> None:
    # берём сохранённый фильтр из state, если был
    data = await state.get_data()
    days = data.get("days")
    category = data.get("category")
    only_top = bool(data.get("only_top", False))

    events = await _fetch_paid_events(limit=FEED_LIMIT, days=days, category=category, only_top=only_top)
    await _send_feed(message, events)


@router.message(F.text == "📅 По дате")
async def resident_choose_date(message: Message, state: FSMContext) -> None:
    await state.set_state(ResidentBrowse.choose_date)
    await message.answer("Выбери период:", reply_markup=date_kb())


@router.message(StateFilter(ResidentBrowse.choose_date), F.text.in_(list(DATE_FILTERS.keys())))
async def resident_apply_date(message: Message, state: FSMContext) -> None:
    days = DATE_FILTERS[message.text]
    data = await state.get_data()
    category = data.get("category")
    only_top = bool(data.get("only_top", False))

    await state.update_data(days=days)

    events = await _fetch_paid_events(limit=FEED_LIMIT, days=days, category=category, only_top=only_top)
    await state.set_state(None)
    await _send_feed(message, events)


@router.message(F.text == "🎭 По категории")
async def resident_choose_category(message: Message, state: FSMContext) -> None:
    await state.set_state(ResidentBrowse.choose_category)
    await message.answer("Выбери категорию:", reply_markup=categories_kb())


@router.message(StateFilter(ResidentBrowse.choose_category), F.text.startswith("🎭 "))
async def resident_apply_category(message: Message, state: FSMContext) -> None:
    category = message.text.replace("🎭", "", 1).strip()
    data = await state.get_data()
    days = data.get("days")
    only_top = bool(data.get("only_top", False))

    await state.update_data(category=category)

    events = await _fetch_paid_events(limit=FEED_LIMIT, days=days, category=category, only_top=only_top)
    await state.set_state(None)
    await _send_feed(message, events)


@router.message(F.text == "🔥 ТОП/Рекомендуем")
async def resident_only_top(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    days = data.get("days")
    category = data.get("category")

    await state.update_data(only_top=True)

    events = await _fetch_paid_events(limit=FEED_LIMIT, days=days, category=category, only_top=True)
    await _send_feed(message, events)


@router.message(F.text == "⬅️ Назад")
async def resident_back(message: Message, state: FSMContext) -> None:
    # просто очищаем state; главное меню остаётся у /start (как у тебя уже сделано)
    await state.clear()
    await message.answer("Ок 👍 Возвращаю в главное меню. Нажми /start")