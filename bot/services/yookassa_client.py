# bot/services/yookassa_client.py
from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

import aiohttp


YOOKASSA_API = "https://api.yookassa.ru/v3/payments"


@dataclass
class YooPayment:
    id: str
    status: str
    confirmation_url: Optional[str]
    raw: Dict[str, Any]


def _basic_auth_header(shop_id: str, secret_key: str) -> str:
    token = f"{shop_id}:{secret_key}".encode("utf-8")
    b64 = base64.b64encode(token).decode("ascii")
    return f"Basic {b64}"


async def create_payment(
    *,
    shop_id: str,
    secret_key: str,
    amount_rub: int,
    description: str,
    return_url: str,
    metadata: Optional[Dict[str, Any]] = None,
    idempotence_key: Optional[str] = None,
) -> YooPayment:
    """
    Создаёт платеж в ЮKassa и возвращает confirmation_url (куда отправлять пользователя).
    """
    if amount_rub <= 0:
        raise ValueError("amount_rub must be > 0")

    idem = idempotence_key or str(uuid.uuid4())
    headers = {
        "Authorization": _basic_auth_header(shop_id, secret_key),
        "Idempotence-Key": idem,
        "Content-Type": "application/json",
    }

    payload = {
        "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": return_url},
        "capture": True,
        "description": description,
        "metadata": metadata or {},
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(YOOKASSA_API, headers=headers, data=json.dumps(payload)) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                raise RuntimeError(f"YooKassa create_payment error {resp.status}: {data}")

    confirmation_url = None
    conf = data.get("confirmation") or {}
    if isinstance(conf, dict):
        confirmation_url = conf.get("confirmation_url")

    return YooPayment(
        id=str(data.get("id")),
        status=str(data.get("status")),
        confirmation_url=confirmation_url,
        raw=data,
    )


async def get_payment(
    *,
    shop_id: str,
    secret_key: str,
    payment_id: str,
) -> YooPayment:
    headers = {"Authorization": _basic_auth_header(shop_id, secret_key)}

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{YOOKASSA_API}/{payment_id}", headers=headers) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                raise RuntimeError(f"YooKassa get_payment error {resp.status}: {data}")

    confirmation_url = None
    conf = data.get("confirmation") or {}
    if isinstance(conf, dict):
        confirmation_url = conf.get("confirmation_url")

    return YooPayment(
        id=str(data.get("id")),
        status=str(data.get("status")),
        confirmation_url=confirmation_url,
        raw=data,
    )