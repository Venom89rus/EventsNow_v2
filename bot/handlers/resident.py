# bot/handlers/resident.py


from __future__ import annotations

import json
import sqlite3
import html
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
    # красивые разные значки + подписи с большой буквы
    ICONS = {
        "концерт": "🎵",
        "спектакль": "🎭",
        "мастер-класс": "🧑‍🎓",
        "выставка": "🖼️",
        "лекция": "🎤",
        "другое": "✨",
    }

    def pretty_name(s: str) -> str:
        s = (s or "").strip()
        return s[:1].upper() + s[1:] if s else s

    rows = []
    cats = RESIDENT_CATEGORIES[:]  # ["концерт", "спектакль", ...]
    for i in range(0, len(cats), 2):
        c1 = cats[i]
        b1 = KeyboardButton(text=f"{ICONS.get(c1, '🎭')} {pretty_name(c1)}")
        row = [b1]

        if i + 1 < len(cats):
            c2 = cats[i + 1]
            b2 = KeyboardButton(text=f"{ICONS.get(c2, '🎭')} {pretty_name(c2)}")
            row.append(b2)

        rows.append(row)

    rows.append([KeyboardButton(text="⬅️ Назад")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


@dataclass
class EventCard:
    id: int
    title: str
    category: str
    category_text: str
    description: str
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


_DB_PATH_PRINTED = False

async def _get_first_photo_file_id(event_id: int) -> str | None:
    global _DB_PATH_PRINTED
    db = get_db()

    # 1) Печатаем путь к SQLite один раз за запуск
    if not _DB_PATH_PRINTED:
        try:
            cur0 = await db.execute("PRAGMA database_list;")
            rows0 = await cur0.fetchall()
            print("DEBUG DB PATH:", rows0[0][2] if rows0 else None)
        except Exception as ex:
            print("WARN: cannot read PRAGMA database_list:", ex)
        _DB_PATH_PRINTED = True

    # 2) Достаём фото из event_photos
    cur = await db.execute(
        """
        SELECT file_id
        FROM event_photos
        WHERE event_id = ?
        ORDER BY position ASC, id ASC
        LIMIT 1
        """,
        (event_id,),
    )
    row = await cur.fetchone()

    if not row:
        print(f"DEBUG PHOTO: event_id={event_id} -> NONE (no rows in event_photos)")
        return None

    try:
        file_id = row["file_id"]
    except Exception:
        file_id = row[0]

    file_id = str(file_id).strip() if file_id else ""
    print(f"DEBUG PHOTO: event_id={event_id} -> {file_id[:12]}... len={len(file_id)}")

    return file_id or None


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
        date({norm_start}) DESC,
        COALESCE(event_time,'') DESC,
        id DESC
    """

    sql = f"""
    SELECT
        id,
        title,
        category,
        category_text,
        COALESCE(description, '') AS description,
        start_date,
        event_date,
        event_time,
        location,
        price_text,
        ticket_link,
        promoted_kind,
        highlighted
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
                description=str(r["description"] or ""),
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

    desc = (e.description or "").strip()
    if desc:
        desc = html.escape(desc)
        if len(desc) > 350:
            desc = desc[:350].rstrip() + "…"
        desc_line = f"📝 {desc}"
    else:
        desc_line = ""

    lines = [
        badge + f"🧾 <b>{e.title}</b>",
        cat_line,
        desc_line,
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

        # 1) Если фото есть — пробуем отправить карточку с фото
        if photo_id:
            try:
                await message.answer_photo(
                    photo=photo_id,
                    caption=text,
                    reply_markup=ikb,
                    parse_mode="HTML",
                )
                continue
            except Exception as ex:
                # Важно: покажем первичную причину, иначе не понять почему фото не ушло
                print(f"WARN: failed to send photo for event_id={e.id}, photo_id={photo_id!r}: {ex}")

        # 2) Фолбэк: отправляем без фото (но с кнопкой если она валидна)
        try:
            await message.answer(text, reply_markup=ikb, parse_mode="HTML")
        except Exception as ex:
            # 3) Последний фолбэк: вообще без клавиатуры (на случай проблем с URL)
            print(f"WARN: failed to send text card with kb for event_id={e.id}: {ex}")
            await message.answer(text, parse_mode="HTML")

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


@router.message(StateFilter(ResidentBrowse.choose_category))
async def resident_apply_category(message: Message, state: FSMContext) -> None:
    txt = (message.text or "").strip()
    if txt == "⬅️ Назад":
        await resident_back(message, state)
        return

    # ожидаем "🎵 Концерт" / "🎭 Спектакль" / ...
    parts = txt.split(maxsplit=1)
    if len(parts) == 2:
        category = parts[1].strip()
    else:
        # если вдруг текст без эмодзи/пробела
        category = txt

    # приводим к нижнему регистру, чтобы совпало с базовой логикой фильтрации
    category = category.lower()

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