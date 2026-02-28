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
import logging
logger = logging.getLogger(__name__)

import asyncio
import uuid

import os
from typing import Any, Optional
from bot.config import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, YOOKASSA_RETURN_URL
from bot.services.yookassa_client import create_payment

router = Router()

def _get_yookassa_credentials() -> tuple[str, str, str]:
    """
    PAYMENT_MODE=0 -> тестовый магазин
    PAYMENT_MODE=1 -> боевой магазин

    Возвращает: (mode, shop_id, secret_key)
    """
    import os

    mode = (os.getenv("PAYMENT_MODE", "1") or "1").strip()
    if mode not in {"0", "1"}:
        mode = "1"

    if mode == "0":
        shop_id = (os.getenv("YOOKASSA_TEST_SHOP_ID", "") or "").strip()
        secret_key = (os.getenv("YOOKASSA_TEST_SECRET_KEY", "") or "").strip()
    else:
        shop_id = (os.getenv("YOOKASSA_SHOP_ID", "") or "").strip()
        secret_key = (os.getenv("YOOKASSA_SECRET_KEY", "") or "").strip()

    if not shop_id or not secret_key:
        raise RuntimeError(
            "Не заданы ключи ЮKassa для выбранного режима. "
            "Проверь .env: PAYMENT_MODE и YOOKASSA_*_SHOP_ID/YOOKASSA_*_SECRET_KEY"
        )

    return mode, shop_id, secret_key

async def create_yookassa_payment(
    *,
    amount: object = None,
    amount_rub: object = None,
    value: object = None,
    description: str = "Оплата услуг",
    return_url: str | None = None,
    idempotence_key: str | None = None,
    metadata: dict | None = None,
    capture: bool = True,
    order_id: object = None,
    event_id: object = None,
    service: object = None,
    organizer_id: object = None,
    **kwargs,
) -> dict:
    """
    Создаёт платеж в YooKassa.
    Возвращает dict (JSON-safe), чтобы можно было сохранять в БД без ошибок.
    """
    import asyncio
    import os
    import uuid
    import json as _json

    from yookassa import Configuration, Payment

    # Выбор TEST/PROD ключей через PAYMENT_MODE
    mode, shop_id, secret_key = _get_yookassa_credentials()
    Configuration.account_id = shop_id
    Configuration.secret_key = secret_key

    # сумма
    raw_amount = None
    for candidate in (amount_rub, amount, value):
        if candidate is not None:
            raw_amount = candidate
            break
    if raw_amount is None:
        raise RuntimeError("Не передана сумма (ожидаю amount_rub/amount/value)")

    try:
        amount_value = float(str(raw_amount).replace(",", "."))
    except Exception:
        raise RuntimeError(f"Не могу распарсить сумму: {raw_amount!r}")

    if amount_value <= 0:
        raise RuntimeError(f"Сумма должна быть > 0, получено: {amount_value}")

    amount_value_str = f"{amount_value:.2f}"

    # return_url
    if not return_url:
        return_url = (os.getenv("YOOKASSA_RETURN_URL", "") or "").strip()

    if not return_url or not str(return_url).startswith("http"):
        raise RuntimeError(
            "Не задан return_url для YooKassa. "
            "Добавь YOOKASSA_RETURN_URL в .env (например https://t.me/Events_Now_bot)"
        )

    # receipt customer (пока оставляем как есть; позже сделаем сбор у пользователя)
    receipt_email = (os.getenv("YOOKASSA_RECEIPT_EMAIL", "") or "").strip()
    receipt_phone = (os.getenv("YOOKASSA_RECEIPT_PHONE", "") or "").strip()
    if not receipt_email and not receipt_phone:
        raise RuntimeError(
            "YooKassa требует чек (receipt), но не задано ни YOOKASSA_RECEIPT_EMAIL, ни YOOKASSA_RECEIPT_PHONE в .env"
        )

    customer: dict = {}
    if receipt_email:
        customer["email"] = receipt_email
    if receipt_phone:
        customer["phone"] = receipt_phone

    # Налоги / чековые поля
    def _int_env(name: str, default: int) -> int:
        try:
            return int((os.getenv(name, str(default)) or str(default)).strip())
        except Exception:
            return default

    tax_system_code = _int_env("YOOKASSA_TAX_SYSTEM_CODE", 1)
    vat_code = _int_env("YOOKASSA_VAT_CODE", 1)

    payment_subject = ((os.getenv("YOOKASSA_PAYMENT_SUBJECT", "service") or "service").strip()) or "service"
    payment_mode = ((os.getenv("YOOKASSA_PAYMENT_MODE", "full_payment") or "full_payment").strip()) or "full_payment"

    item_description = (description or "Оплата услуг").strip()
    if len(item_description) > 128:
        item_description = item_description[:128]

    receipt = {
        "customer": customer,
        "tax_system_code": tax_system_code,
        "items": [
            {
                "description": item_description,
                "quantity": "1.00",
                "amount": {"value": amount_value_str, "currency": "RUB"},
                "vat_code": vat_code,
                "payment_subject": payment_subject,
                "payment_mode": payment_mode,
            }
        ],
    }

    # metadata (сохраняем контекст заказа, чтобы потом webhook/проверки работали)
    meta: dict = {}
    if isinstance(metadata, dict):
        meta.update(metadata)
    if order_id is not None:
        meta["order_id"] = str(order_id)
    if event_id is not None:
        meta["event_id"] = str(event_id)
    if service is not None:
        meta["service"] = str(service)
    if organizer_id is not None:
        meta["organizer_id"] = str(organizer_id)

    payload = {
        "amount": {"value": amount_value_str, "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": str(return_url)},
        "capture": bool(capture),
        "description": description or "Оплата услуг",
        "receipt": receipt,
    }
    if meta:
        payload["metadata"] = meta

    if not idempotence_key:
        idempotence_key = str(uuid.uuid4())

    logger.info(
        "YOOKASSA: mode=%s create payment amount=%s order_id=%s return_url=%s idempotence=%s",
        "TEST" if mode == "0" else "PROD",
        amount_value_str, str(order_id), str(return_url), idempotence_key
    )

    # SDK синхронный — уводим в thread
    payment_obj = await asyncio.to_thread(Payment.create, payload, idempotence_key)

    # Достаём confirmation_url
    confirmation_url = None
    try:
        confirmation_url = payment_obj.confirmation.confirmation_url
    except Exception:
        try:
            if isinstance(payment_obj, dict):
                confirmation_url = (payment_obj.get("confirmation") or {}).get("confirmation_url")
        except Exception:
            confirmation_url = None

    # Главное: возвращаем JSON-safe dict (чтобы set_order_payload/json.dumps не падали)
    # raw кладём как dict если SDK умеет, иначе как строку.
    raw = None
    try:
        if hasattr(payment_obj, "to_dict") and callable(payment_obj.to_dict):
            raw = payment_obj.to_dict()
        elif hasattr(payment_obj, "dict") and callable(payment_obj.dict):
            raw = payment_obj.dict()
        else:
            raw = str(payment_obj)
    except Exception:
        raw = str(payment_obj)

    return {
        "id": getattr(payment_obj, "id", None) or (raw.get("id") if isinstance(raw, dict) else None),
        "status": getattr(payment_obj, "status", None) or (raw.get("status") if isinstance(raw, dict) else None),
        "confirmation_url": confirmation_url,
        "mode": "test" if mode == "0" else "prod",
        "raw": raw,
    }

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
            [InlineKeyboardButton(text="⭐ Топ на 24ч — 299₽", callback_data=f"promo_srv:top:{event_id}")],
            [InlineKeyboardButton(text="📣 Оповещение всем — 199₽", callback_data=f"promo_srv:notify:{event_id}")],
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


def promo_paid_kb(order_id: int, pay_url: str) -> InlineKeyboardMarkup:
    """
    Клавиатура оплаты:
    - URL-кнопка "Оплатить в ЮKassa" ведёт на confirmation_url
    - "✅ Я оплатил" и "❌ Отмена" — callback'и, как в pay_kb (чтобы существующие хендлеры работали)
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить в ЮKassa", url=pay_url)],
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


# ===== handlers =====\

def _get(order, key: str, default=None):
    if order is None:
        return default
    if isinstance(order, dict):
        return order.get(key, default)
    return getattr(order, key, default)

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


@router.callback_query(F.data.startswith("promo:service:"))
async def promo_cb_service(cb: CallbackQuery, state: FSMContext, repo: repo) -> None:
    # пример data: promo:service:top
    service = cb.data.split(":")[-1]

    data = await state.get_data()
    event_id = int(data.get("promo_event_id") or 0)
    if not event_id:
        await cb.answer("Сначала выбери событие", show_alert=True)
        return

    # цены (оставь как у тебя; пример)
    prices = {"top": 299, "notify": 199, "highlight": 149, "bump": 99}
    amount_rub = int(prices.get(service, 0))
    if amount_rub <= 0:
        await cb.answer("Неизвестная услуга", show_alert=True)
        return

    # 1) создаём заказ в БД
    order_id = await repo.create_promo_order(
        organizer_id=cb.from_user.id,
        event_id=event_id,
        service=service,
        amount_rub=amount_rub,
        currency="RUB",
        payload_json="{}",
    )

    # 2) создаём платеж ЮKassa


    pay = await create_payment(
        shop_id=YOOKASSA_SHOP_ID,
        secret_key=YOOKASSA_SECRET_KEY,
        amount_rub=amount_rub,
        description=f"EventsNow: promo {service} для события #{event_id}",
        return_url=YOOKASSA_RETURN_URL,
        metadata={"order_id": order_id, "event_id": event_id, "service": service, "user_id": cb.from_user.id},
    )

    payment = await create_yookassa_payment(
        amount_rub=amount_rub,
        description=f"EventsNow: promo {service} для события #{event_id}",
        return_url=YOOKASSA_RETURN_URL,  # если есть
        metadata={"order_id": order_id, "tg_user_id": cb.from_user.id},
    )
    pay_url = payment["confirmation_url"]

    if not pay.confirmation_url:
        await cb.answer("Не удалось получить ссылку оплаты", show_alert=True)
        return

    # 3) сохраняем payment_id/confirmation_url в payload_json (без новых колонок)
    import json
    payload = {"payment_id": pay.id, "confirmation_url": pay.confirmation_url, "status": pay.status}
    await repo.set_promo_payment_data(order_id, pay.id, pay.confirmation_url, json.dumps(payload, ensure_ascii=False))

    # 4) показываем оплату
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить в ЮKassa", url=pay.confirmation_url)],
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"promo:paid:{order_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="promo:cancel")],
        ]
    )

    await cb.message.answer(
        f"🧾 <b>Оплата</b>\n\n"
        f"Услуга: <b>{service}</b>\n"
        f"Событие: <b>{event_id}</b>\n"
        f"Сумма: <b>{amount_rub}₽</b>\n\n"
        f"1) Нажми «Оплатить в ЮKassa»\n"
        f"2) После оплаты вернись и нажми «✅ Я оплатил»",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("promo_paid:"))
async def promo_cb_paid(cb: CallbackQuery, repo: "Repo" = None) -> None:
    import asyncio
    import logging

    from bot.db.repositories import repo as _repo
    if repo is None:
        repo = _repo

    log = logging.getLogger(__name__)

    parts = (cb.data or "").split(":")
    if len(parts) != 2 or not parts[1].isdigit():
        await cb.answer("Некорректная кнопка.", show_alert=True)
        return

    order_id = int(parts[1])

    order = await repo.get_order(order_id)
    if not order:
        await cb.answer("Заказ не найден.", show_alert=True)
        return

    organizer_id = getattr(order, "organizer_id", None)
    if organizer_id is None or int(organizer_id) != int(cb.from_user.id):
        await cb.answer("Это не твой заказ.", show_alert=True)
        return

    # --- достаём payment_id из заказа ---
    payload = getattr(order, "payload_json", {}) or {}
    payment_id = None
    if isinstance(payload, dict):
        payment_id = payload.get("id") or payload.get("payment_id")
        if not payment_id and isinstance(payload.get("raw"), dict):
            payment_id = payload["raw"].get("id")

    if not payment_id:
        payment_id = getattr(order, "yk_payment_id", None)

    if not payment_id:
        await cb.answer("Не найден payment_id по этому заказу.", show_alert=True)
        return

    # --- Проверяем статус платежа в YooKassa (ВАЖНО: теми же ключами TEST/PROD) ---
    try:
        from yookassa import Configuration, Payment

        # Используем твой переключатель режимов
        mode, shop_id, secret_key = _get_yookassa_credentials()
        Configuration.account_id = shop_id
        Configuration.secret_key = secret_key

        payment_obj = await asyncio.to_thread(Payment.find_one, str(payment_id))
        status = getattr(payment_obj, "status", None)

        log.info(
            "YOOKASSA: mode=%s check payment_id=%s status=%s order_id=%s",
            "TEST" if mode == "0" else "PROD",
            str(payment_id),
            str(status),
            str(order_id),
        )
    except Exception as e:
        log.exception("YOOKASSA: failed to check payment status payment_id=%s order_id=%s", payment_id, order_id)
        await cb.answer("Не удалось проверить оплату. Попробуй чуть позже.", show_alert=True)
        return

    if status != "succeeded":
        await cb.answer("Оплата ещё не подтверждена YooKassa. Попробуй через 10–30 сек.", show_alert=True)
        return

    # --- отмечаем paid + применяем услугу ---
    await repo.mark_order_paid(order_id, yk_payment_id=str(payment_id))
    await repo.set_event_promoted(int(order.event_id), kind=str(order.service))

    await cb.message.answer("✅ Оплата подтверждена YooKassa. Продвижение применено к событию!")
    await cb.answer()


@router.callback_query(F.data.startswith("promo_cancel:"))
async def promo_cb_cancel(cb: CallbackQuery) -> None:
    await cb.message.answer("❌ Отменено.", reply_markup=promo_menu_kb())
    await cb.answer()

@router.callback_query(F.data.startswith("promo_srv:"))
async def promo_cb_service(cb: CallbackQuery, repo: "Repo" = None) -> None:
    from bot.db.repositories import repo as _repo
    if repo is None:
        repo = _repo

    data = (cb.data or "").strip()
    parts = data.split(":")  # promo_srv:<service>:<event_id>
    if len(parts) != 3:
        await cb.answer("Некорректная кнопка.", show_alert=True)
        return

    _, service, event_id_str = parts
    if not event_id_str.isdigit():
        await cb.answer("Некорректный ID события.", show_alert=True)
        return
    event_id = int(event_id_str)

    prices = {"top": 99, "highlight": 199, "bump": 99, "notify": 499}
    if service not in prices:
        await cb.answer("Неизвестная услуга.", show_alert=True)
        return
    amount_rub = int(prices[service])

    # 1) создаём заказ
    order_id = await repo.create_promo_order(
        organizer_id=int(cb.from_user.id),
        event_id=event_id,
        service=service,
        amount_rub=amount_rub,
        currency="RUB",
        payload_json="{}",
    )

    # 2) создаём платёж YooKassa
    payment = await create_yookassa_payment(
        amount_rub=amount_rub,
        description=f"EventsNow: promo {service} для события #{event_id}",
        return_url=os.getenv("YOOKASSA_RETURN_URL", "").strip(),
        metadata={"order_id": order_id, "event_id": event_id, "service": service, "tg_user_id": cb.from_user.id},
        order_id=order_id,
        event_id=event_id,
        service=service,
        organizer_id=cb.from_user.id,
    )

    pay_url = payment.get("confirmation_url")
    if not pay_url:
        await cb.answer("Не удалось получить ссылку оплаты.", show_alert=True)
        return

    # 3) сохраняем payload
    await repo.set_order_payload(order_id, payment)

    # 4) показываем пользователю
    await cb.message.answer(
        f"🧾 <b>Оплата</b>\n\n"
        f"Услуга: <b>{service}</b>\n"
        f"Событие: <b>{event_id}</b>\n"
        f"Сумма: <b>{amount_rub}₽</b>\n\n"
        f"1) Нажми «Оплатить в ЮKassa»\n"
        f"2) После оплаты нажми «✅ Я оплатил»",
        reply_markup=promo_paid_kb(order_id, pay_url),
    )
    await cb.answer()
@router.callback_query()
async def _debug_any_callback(cb: CallbackQuery):
    logger.warning("UNHANDLED CALLBACK: data=%r", cb.data)
    await cb.answer("Кнопка нажалась, но хендлер не найден 😕", show_alert=True)