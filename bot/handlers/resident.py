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
    category: str
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

    db = get_db()

    now_dt = datetime.now()
    today = now_dt.date()
    now_time = now_dt.strftime("%H:%M:%S")

    date_to = None
    if days is not None:
        date_to = today + timedelta(days=max(days - 1, 0))

    where = ["status = 'approved'"]
    params: list[object] = []

    # ВАЖНО: пустые строки считаем как NULL, иначе COALESCE возьмёт '' и date('') станет NULL.
    def _nn(col: str) -> str:
        return f"NULLIF(trim({col}), '')"

    best_start = f"COALESCE({_nn('sessions_start_date')}, {_nn('start_date')}, {_nn('event_date')})"
    best_end = f"COALESCE({_nn('sessions_end_date')}, {_nn('end_date')}, {_nn('sessions_start_date')}, {_nn('start_date')}, {_nn('event_date')})"

    def norm_date_expr(expr: str) -> str:
        e = f"trim({expr})"
        return f"""
        CASE
            WHEN {e} LIKE '__.__.____'
            THEN substr({e}, 7, 4) || '-' || substr({e}, 4, 2) || '-' || substr({e}, 1, 2)
            ELSE {e}
        END
        """.strip()

    norm_start = norm_date_expr(best_start)
    norm_end = norm_date_expr(best_end)

    # Если даты вообще нет (NULL) — такое событие не показываем в ленте
    where.append(f"COALESCE(trim({best_start}), '') <> ''")


    where.append(
        f"""(
            date({norm_end}) > date(?)
            OR (
                date({norm_end}) = date(?)
                AND (
                    COALESCE(trim(event_time),'') = ''
                    OR time(
                    CASE
                        WHEN length(trim(event_time)) = 5 THEN trim(event_time) || ':00'
                        ELSE trim(event_time)
                    END
                    ) >= time(?)
                )
            )
        )"""
    )
    params.extend([today.isoformat(), today.isoformat(), now_time])

    # Ограничение "до N дней" (по дате старта)
    if date_to is not None:
        where.append(f"date({norm_start}) <= date(?)")
        params.append(date_to.isoformat())

    if category:
        cat = category.strip()
        cat_cap = cat[:1].upper() + cat[1:] if cat else cat
        cat_up = cat.upper()

        where.append(
            "("
            "COALESCE(category,'') LIKE '%' || ? || '%' OR "
            "COALESCE(category,'') LIKE '%' || ? || '%' OR "
            "COALESCE(category,'') LIKE '%' || ? || '%' OR "
            "COALESCE(category_text,'') LIKE '%' || ? || '%' OR "
            "COALESCE(category_text,'') LIKE '%' || ? || '%' OR "
            "COALESCE(category_text,'') LIKE '%' || ? || '%'"
            ")"
        )
        params.extend([cat, cat_cap, cat_up, cat, cat_cap, cat_up])

    # ТОП/Рекомендуем: только продвинутые (notify сюда НЕ входит)
    if only_top:
        where.append(
            """(
                lower(trim(COALESCE(promoted_kind,''))) IN ('top','highlight','bump','топ','подсветка')
                OR COALESCE(highlighted,0) = 1
                OR COALESCE(bumped_at,'') <> ''
            )"""
        )

    where_sql = " AND ".join(where)

    order_by = f"""
        CASE
            WHEN lower(trim(COALESCE(promoted_kind,''))) IN ('top','топ') THEN 0
            WHEN COALESCE(highlighted,0) = 1 OR lower(trim(COALESCE(promoted_kind,''))) IN ('highlight','подсветка') THEN 1
            WHEN lower(trim(COALESCE(promoted_kind,''))) IN ('bump') OR COALESCE(bumped_at,'') <> '' THEN 2
            ELSE 3
        END,
        COALESCE(highlighted,0) DESC,
        COALESCE(bumped_at,'') DESC,
        date({norm_start}) ASC,
        COALESCE(event_time,'') ASC,
        id DESC
    """

    sql = f"""
    SELECT
        id, title, category, category_text,
        start_date, event_date, event_time,
        location, price_text, ticket_link,
        promoted_kind, highlighted
    FROM events
    WHERE {where_sql}
    ORDER BY {order_by}
    LIMIT ?
    """
    params.append(int(limit))

    cur = await db.execute(sql, tuple(params))
    rows = await cur.fetchall()
    print("DEBUG resident feed:", len(rows), "days=", days, "category=", category, "only_top=", only_top, "params=",
          params)

    out: list[EventCard] = []
    for r in rows:
        out.append(
            EventCard(
                id=int(r["id"]),
                title=str(r["title"] or ""),
                category=str(r["category"] or ""),
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

    # category в базе реально заполнен (с эмодзи), category_text может быть пустым
    cat_raw = (getattr(e, "category", "") or "").strip()
    if not cat_raw:
        cat_raw = (e.category_text or "").strip()

    cat_line = f"🎭 <b>Категория:</b> {cat_raw}" if cat_raw else ""

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
    lines = [x for x in lines if x]
    return "\n".join(lines)


def _ticket_kb(e: EventCard) -> InlineKeyboardMarkup | None:
    link = (e.ticket_link or "").strip()
    if not link:
        return None

    bad_values = {"нет", "no", "-", "—", "n/a", "не указано", "отсутствует"}
    if link.lower() in bad_values:
        return None

    if not (link.startswith("http://") or link.startswith("https://")):
        return None

    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🎟 Купить билет", url=link)]]
    )


async def _send_feed(message: Message, events: list[EventCard]) -> None:
    if not events:
        await message.answer(
            "Пока нет подходящих мероприятий 🙁\n\n"
            "Попробуй изменить фильтр или зайди позже.",
            reply_markup=resident_menu_kb(),
        )
        return

    await message.answer(
        "🗓 Показываю мероприятия (до 10 шт.).\n"
        "Фильтры — кнопками снизу 👇",
        reply_markup=resident_menu_kb(),
    )

    for e in events:
        photo_id = await _get_first_photo_file_id(e.id)
        text = _format_card_text(e)
        ikb = _ticket_kb(e)

        try:
            if photo_id:
                await message.answer_photo(photo=photo_id, caption=text, reply_markup=ikb)
            else:
                await message.answer(text, reply_markup=ikb)
        except Exception as ex:
            # Фолбэк: без клавиатуры/кнопок
            try:
                if photo_id:
                    await message.answer_photo(photo=photo_id, caption=text)
                else:
                    await message.answer(text)
            except Exception:
                print("WARN: failed to send event card", e.id, ex)


@router.message(F.text == "🏠 Житель")
async def resident_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    # Житель = платная лента (только продвинутые). notify не попадает (это уже в SQL only_top)
    await state.update_data(only_top=True, days=None, category=None)

    events = await _fetch_paid_events(limit=FEED_LIMIT, only_top=True)
    await _send_feed(message, events)


@router.message(F.text == "🔄 Обновить")
async def resident_refresh(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    days = data.get("days")
    category = data.get("category")
    only_top = bool(data.get("only_top", True))  # по умолчанию считаем, что режим "Житель" платный

    events = await _fetch_paid_events(limit=FEED_LIMIT, days=days, category=category, only_top=only_top)
    await _send_feed(message, events)


@router.message(F.text == "📅 По дате")
async def resident_choose_date(message: Message, state: FSMContext) -> None:
    await state.set_state(ResidentBrowse.choose_date)
    await message.answer("Выбери период:", reply_markup=date_kb())


@router.message(StateFilter(ResidentBrowse.choose_date), F.text.in_(list(DATE_FILTERS.keys())))
async def resident_apply_date(message: Message, state: FSMContext) -> None:
    days = DATE_FILTERS[message.text]

    # Период выбран — сбрасываем категорию, чтобы фильтры не наслаивались
    await state.update_data(days=days, category=None, only_top=False)

    events = await _fetch_paid_events(limit=FEED_LIMIT, days=days, category=None, only_top=False)
    await state.set_state(None)
    await _send_feed(message, events)


@router.message(F.text == "🎭 По категории")
async def resident_choose_category(message: Message, state: FSMContext) -> None:
    await state.set_state(ResidentBrowse.choose_category)
    await message.answer("Выбери категорию:", reply_markup=categories_kb())


@router.message(StateFilter(ResidentBrowse.choose_category), F.text.startswith("🎭 "))
async def resident_apply_category(message: Message, state: FSMContext) -> None:
    category = message.text.replace("🎭", "", 1).strip()

    # Категория выбрана — сбрасываем период, чтобы фильтры не наслаивались
    await state.update_data(category=category, days=None, only_top=False)

    events = await _fetch_paid_events(limit=FEED_LIMIT, days=None, category=category, only_top=False)
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