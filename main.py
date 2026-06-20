"""Точка входа: инициализация бота, загрузка модели, запуск polling."""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import router
from bot.middleware import HistoryWriterMiddleware
from config import settings
from llm.engine import get_llama

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("chatbot")


def validate_env() -> None:
    if not settings.bot_token or settings.bot_token.startswith("123456:"):
        raise RuntimeError(
            "BOT_TOKEN не задан или некорректен. Создай .env из .env.example."
        )
    if not settings.bot_username:
        log.warning(
            "BOT_USERNAME не задан — нативный @mention-триггер работать не будет. "
            "Укажи username бота (без @) в .env."
        )
    if not settings.model_path.exists():
        raise RuntimeError(
            f"Файл модели не найден: {settings.model_path}. "
            "Положи GGUF в models/ и/или проверь MODEL_PATH в .env."
        )


async def main_async() -> None:
    validate_env()

    # Предзагружаем модель до приёма апдейтов (это занимает ~10-20 секунд).
    log.info("Preloading model…")
    await asyncio.to_thread(get_llama)
    log.info("Model ready.")

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    me = await bot.get_me()
    log.info("Bot identity: @%s (id=%d)", me.username, me.id)
    # Если username задан в env — перетрём дефолт актуальным
    if not settings.bot_username:
        # pydantic-settings: field assignment disabled by default
        # используем _secret_mutate через object.__setattr__
        object.__setattr__(settings, "bot_username", me.username or "")

    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(HistoryWriterMiddleware())
    dp.include_router(router)

    log.info("Starting polling…")
    await dp.start_polling(bot, allowed_updates=None)
    await bot.session.close()


def main() -> None:
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutdown.")


if __name__ == "__main__":
    main()
