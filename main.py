"""Точка входа: инициализация бота, проверка LLM-сервера, запуск polling."""
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
from llm.engine import check_health

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
    if not settings.llm_base_url:
        raise RuntimeError("LLM_BASE_URL не задан в .env.")


async def main_async() -> None:
    validate_env()

    # Проверяем доступность LLM-сервера (llama-server на ноуте через туннель).
    log.info("Checking LLM server at %s …", settings.llm_base_url)
    await check_health()
    log.info("LLM server ready.")

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
