# bot/handlers/promo.py
from __future__ import annotations

import uuid
import base64
from dataclasses import dataclass
from typing import Optional

import aiohttp
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from bot.config import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY

router = Router()


# =========================
# FSM
# =========================
class PromoFlow(StatesGroup):
    wait_event_id = State()


# =========================
# UI
# =========================
def promo_menu_kb(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📣 Оповещение всем (разово)", callback_data=f"promo:svc:broadcast:{event_id}")],
            [InlineKeyboardButton(text="⭐ В топ на 7 дней", callback_data=f"promo:svc:top7:{event_id}")],
            [InlineKeyboardButton(text="📌 Закреп на 3 дня", callback_data=f"promo:svc:pin3:{event_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="promo:cancel")],
        ]
    )


def pay_kb(pay_url: str, payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=pay_url)],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"promo:check:{payment_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="promo:cancel")],
        ]
    )


# =========================
# YOOKASSA HTTP (без SDK)
# =========================
@dataclass
class PaymentCreateResult:
    payment_id: str
    status: str
    confirmation_url: str


def _basic_auth_header(shop_id: str, secret_key: str) -> str:
    token = base64.b64encode(f"{shop_id}:{secret_key}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


async def yk_create_payment(
    *,
    amount_rub: int,
    description: str,
    return_url: str,
    metadata: dict,
) -> PaymentCreateResult:
    # https://yookassa.ru/developers/api#create_payment (делаем через aiohttp)
    url = "https://api.yookassa.ru/v3/payments"
    idem_key = str(uuid.uuid4())

    headers = {
        "Authorization": _basic_auth_header(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY),
        "Idempotence-Key": idem_key,
        "Content-Type": "application/json",
    }

    payload = {
        "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": return_url},
        "capture": True,
        "description": description,
        "metadata": metadata,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=30) as resp:
            data = await resp.json()
            if resp.status >= 400:
                raise RuntimeError(f"YooKassa error: {data}")
            return PaymentCreateResult(
                payment_id=data["id"],
                status=data.get("status", ""),
                confirmation_url=data["confirmation"]["confirmation_url"],
            )


async def yk_get_payment(payment_id: str) -> dict:
    url = f"https://api.yookassa.ru/v3/payments/{payment_id}"
    headers = {
        "Authorization": _basic_auth_header(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY),
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=30) as resp:
            data = await resp.json()
            if resp.status >= 400:
                raise RuntimeError(f"YooKassa error: {data}")
            return data


# =========================
# PRICES (потом вынесем в конфиг/БД)
# =========================
SERVICE_PRICES = {
    "broadcast": 199,  # руб
    "top7": 299,
    "pin3": 249,
}


SERVICE_TITLES = {
    "broadcast": "Оповещение всем (разово)",
    "top7": "В топ на 7 дней",
    "pin3": "Закреп на 3 дня",
}


# =========================
# ENTRY
# =========================
@router.message(F.text == "/promo")
async def promo_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(PromoFlow.wait_event_id)
    await message.answer(
        "📈 <b>Продвижение</b>\n\n"
        "Введи <b>ID мероприятия</b>, которое хочешь продвинуть.\n"
        "Пример: <code>12</code>"
    )


@router.message(PromoFlow.wait_event_id)
async def promo_take_event_id(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("⚠️ Нужен числовой ID. Пример: <code>12</code>")
        return

    event_id = int(text)
    await state.clear()
    await message.answer(
        f"Выбери услугу для события <b>ID {event_id}</b> 👇",
        reply_markup=promo_menu_kb(event_id),
    )


@router.callback_query(F.data == "promo:cancel")
async def promo_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.answer("❌ Ок, отменил.")
    await cb.answer()


@router.callback_query(F.data.startswith("promo:svc:"))
async def promo_choose_service(cb: CallbackQuery) -> None:
    # promo:svc:<service>:<event_id>
    _, _, service, event_id_s = cb.data.split(":")
    event_id = int(event_id_s)

    if service not in SERVICE_PRICES:
        await cb.answer("Неизвестная услуга", show_alert=True)
        return

    price = SERVICE_PRICES[service]
    title = SERVICE_TITLES[service]

    # return_url можно поставить любой (хоть на твой сайт, хоть на заглушку)
    # ЮKassa требует валидный URL. Если сайта нет — ставь https://t.me/<botname>
    return_url = "https://t.me/Events_Now_bot"

    description = f"EventsNow: {title} для события #{event_id}"
    metadata = {
        "service": service,
        "event_id": event_id,
        "tg_user_id": cb.from_user.id,
    }

    try:
        res = await yk_create_payment(
            amount_rub=price,
            description=description,
            return_url=return_url,
            metadata=metadata,
        )
    except Exception as e:
        await cb.message.answer(f"❌ Ошибка создания платежа:\n<code>{e}</code>")
        await cb.answer()
        return

    await cb.message.answer(
        "✅ Платёж создан.\n\n"
        f"Услуга: <b>{title}</b>\n"
        f"Сумма: <b>{price} ₽</b>\n\n"
        "Нажми «Оплатить», потом вернись и нажми «Проверить оплату».",
        reply_markup=pay_kb(res.confirmation_url, res.payment_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("promo:check:"))
async def promo_check(cb: CallbackQuery) -> None:
    payment_id = cb.data.split(":")[2]

    try:
        data = await yk_get_payment(payment_id)
    except Exception as e:
        await cb.answer("Ошибка проверки", show_alert=True)
        await cb.message.answer(f"❌ Ошибка проверки платежа:\n<code>{e}</code>")
        return

    status = data.get("status", "unknown")
    paid = status == "succeeded"

    if not paid:
        await cb.answer("Пока не оплачено", show_alert=True)
        await cb.message.answer(
            f"⏳ Платёж <b>{payment_id}</b> пока не подтверждён.\n"
            f"Статус: <b>{status}</b>\n\n"
            "Если ты только что оплатил — попробуй через 5–10 секунд ещё раз."
        )
        return

    # ✅ Тут будет “активация услуги”:
    # на этом шаге мы НЕ трогаем твою БД, чтобы ничего не сломать.
    # Дальше сделаем отдельную табличку promo_orders и начнём реально включать “топ/закреп/рассылка”.
    meta = (data.get("metadata") or {})
    service = meta.get("service", "")
    event_id = meta.get("event_id", "")
    title = SERVICE_TITLES.get(service, service)

    await cb.message.answer(
        "✅ <b>Оплата прошла!</b>\n\n"
        f"Платёж: <code>{payment_id}</code>\n"
        f"Услуга: <b>{title}</b>\n"
        f"Событие: <b>{event_id}</b>\n\n"
        "Следующий шаг: подключаем запись в SQLite и фактическое выполнение услуги (топ/закреп/рассылка)."
    )
    await cb.answer("Оплачено ✅")