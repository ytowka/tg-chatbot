"""Определение, нужно ли отвечать на сообщение группы."""
from __future__ import annotations

import random
from typing import Any

from aiogram.types import Message

from config import settings
from storage import features


def _normalize_username(s: str) -> str:
    return s.lower().lstrip("@")


def is_bot_mention_entity(message: Message) -> bool:
    """Telegram-native @username mention через entities типа 'mention'."""
    bot_username = _normalize_username(settings.bot_username)
    if not bot_username:
        return False
    entities = message.entities or []
    text = message.text or message.caption or ""
    for ent in entities:
        if ent.type == "mention":
            mention = text[ent.offset : ent.offset + ent.length].strip()
            if _normalize_username(mention) == bot_username:
                return True
        elif ent.type == "text_mention" and ent.user:
            # Если у пользователя нет username — Telegram использует text_mention
            # Мы не можем быть увереным, что это бот, без id. Сравниваем по id,
            # если бот сам сообщил свой id в me (вызывающий код может прокинуть).
            pass
    return False


def has_trigger_phrase(text: str) -> bool:
    """Case-insensitive поиск триггерной фразы в тексте."""
    phrase = settings.trigger_phrase.strip().lower()
    if not phrase:
        return False
    return phrase in (text or "").lower()


def is_reply_to_bot(message: Message, bot_user_id: int | None) -> bool:
    """Сообщение является reply на сообщение бота."""
    if bot_user_id is None:
        return False
    reply = message.reply_to_message
    if reply is None:
        return False
    reply_from = reply.from_user
    return reply_from is not None and reply_from.id == bot_user_id


def should_random_reply(message: Message, bot_user_id: int | None) -> bool:
    """Случайный ответ на любое сообщение с заданной вероятностью.

    Условия срабатывания:
      - флаг random_reply включён (переключается командой /randomreply);
      - сообщение не является командой (не начинается с '/');
      - отправитель — не сам бот;
      - random.random() < settings.random_reply_chance.
    """
    if not features.is_random_reply_enabled():
        return False
    text = message.text or message.caption or ""
    if text.startswith("/"):
        return False
    if (
        bot_user_id is not None
        and message.from_user is not None
        and message.from_user.id == bot_user_id
    ):
        return False
    return random.random() < settings.random_reply_chance


def should_reply(message: Message, bot_user_id: int | None) -> bool:
    """Сводный триггер: отвечать, если упоминание / фраза / reply на бота / случайный ответ."""
    text = message.text or message.caption or ""
    if not text:
        return False
    if has_trigger_phrase(text):
        return True
    if is_bot_mention_entity(message):
        return True
    if is_reply_to_bot(message, bot_user_id):
        return True
    if should_random_reply(message, bot_user_id):
        return True
    return False


def strip_trigger(text: str) -> str:
    """Удалить триггерную фразу и @mention из текста запроса перед отправкой в LLM."""
    out = text or ""
    phrase = settings.trigger_phrase.strip()
    if phrase:
        # удаляем первое вхождение (case-insensitive)
        idx = out.lower().find(phrase.lower())
        if idx != -1:
            out = out[:idx] + out[idx + len(phrase) :]
    bot_username = settings.bot_username.lstrip("@")
    if bot_username:
        out = out.replace("@" + bot_username, "")
    return out.strip()
