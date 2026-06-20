"""aiogram middleware: запись всех входящих сообщений в history."""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message

from config import settings
from storage import history
from bot import triggers

log = logging.getLogger(__name__)


class HistoryWriterMiddleware(BaseMiddleware):
    """Каждое текстовое сообщение группы пишется в history.jsonl.

    Не фильтрует триггеры — просто фиксирует факт сообщения и его атрибуты
    (было ли оно упоминанием/ответом боту). Решение, отвечать или нет,
    принимает handler через triggers.should_reply().
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            message = event
            text = message.text or message.caption or ""
            # Пишем только текстовые (медиа игнорируем в MVP)
            if text and message.from_user is not None:
                bot = data.get("bot")
                bot_user_id = bot.id if bot else None
                try:
                    history.append(
                        {
                            "ts": time.time(),
                            "chat_id": message.chat.id,
                            "message_id": message.message_id,
                            "user_id": message.from_user.id,
                            "username": message.from_user.username
                            or message.from_user.first_name
                            or str(message.from_user.id),
                            "first_name": message.from_user.first_name or "",
                            "text": text,
                            "is_bot_mention": triggers.has_trigger_phrase(text)
                            or triggers.is_bot_mention_entity(message),
                            "is_reply_to_bot": triggers.is_reply_to_bot(
                                message, bot_user_id
                            ),
                        }
                    )
                except Exception:
                    log.exception("failed to write message to history")
        return await handler(event, data)
