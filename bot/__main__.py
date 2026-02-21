import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart

from bot.config import API_TOKEN, DATABASE_URL
from bot.handlers.organizer import router as organizer_router
from bot.handlers.resident import router as resident_router
from bot.handlers.admin import router as admin_router

from bot.db.database import init_db, close_db
from bot.db.schema import ensure_schema

logging.basicConfig(level=logging.INFO)


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


async def on_startup() -> None:
    await init_db(DATABASE_URL)
    await ensure_schema()
    logging.info("✅ SQLite DB ready")


async def on_shutdown() -> None:
    await close_db()
    logging.info("✅ SQLite closed")


async def main() -> None:
    bot = Bot(
        token=API_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(organizer_router)
    dp.include_router(resident_router)
    dp.include_router(admin_router)

    @dp.message(CommandStart())
    async def cmd_start(message: Message) -> None:
        await message.answer(
            "👋 Привет! Это <b>EventsNow</b>\n\n"
            "<b>Проводник по мероприятиям ТВОЕГО города</b>\n\n"
            "Выбирай раздел и поехали 🚀",
            reply_markup=main_menu_kb(),
        )

    @dp.message(F.text == "📞 Обратная связь")
    async def feedback(message: Message) -> None:
        await message.answer("📩 Напиши своё сообщение — мы обязательно ответим!")

    await on_startup()
    try:
        await dp.start_polling(bot)
    finally:
        await on_shutdown()


if __name__ == "__main__":
    asyncio.run(main())