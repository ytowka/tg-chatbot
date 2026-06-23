"""Handlers: /start, /reset, /summary, текстовый триггер."""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import re
from contextlib import suppress
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from zoneinfo import ZoneInfo

from config import settings
from llm import engine, prompts
from storage import context as context_store
from storage import features, history, memory
from bot import triggers

log = logging.getLogger(__name__)
router = Router()

# Per-user блокировка, чтобы запросы одного пользователя не соревновались за инстанс LLM.
_user_locks: dict[int, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


_MD_DOUBLE_ASTERISK = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MD_DOUBLE_UNDERSCORE = re.compile(r"__(.+?)__", re.DOTALL)
_MD_BACKTICK = re.compile(r"`(.+?)`", re.DOTALL)
_MD_HEADER = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_BULLET = re.compile(r"^\s*\*\s+", re.MULTILINE)


def _strip_markdown(text: str) -> str:
    """Убрать markdown-разметку — Telegram получает plain text."""
    text = _MD_DOUBLE_ASTERISK.sub(r"\1", text)
    text = _MD_DOUBLE_UNDERSCORE.sub(r"\1", text)
    text = _MD_BACKTICK.sub(r"\1", text)
    text = _MD_HEADER.sub("", text)
    text = _MD_BULLET.sub("", text)
    return text


async def _get_user_lock(user_id: int) -> asyncio.Lock:
    async with _locks_guard:
        if user_id not in _user_locks:
            _user_locks[user_id] = asyncio.Lock()
        return _user_locks[user_id]


# ─────────────────────────────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────────────────────────────
@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    name = settings.trigger_phrase.capitalize()
    await message.answer(
        f"Привет! Я {name}, ассистент этой группы.\n\n"
        f"Обратитесь ко мне, написав «{settings.trigger_phrase}» или @{settings.bot_username}, "
        "либо ответив (reply) на моё сообщение.\n\n"
        "Команды:\n"
        "/summary — сводка вчерашних сообщений\n"
        "/reset — очистить контекст диалога\n"
        "/randomreply — включить/выключить случайные ответы"
    )


# ─────────────────────────────────────────────────────────────────────
# /reset — принудительная очистка контекста (с обновлением памяти)
# ─────────────────────────────────────────────────────────────────────
@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    status = await message.answer("⏳ Сохраняю контекст в память перед очисткой…")
    try:
        await _maybe_compact_memory()
    except Exception:
        log.exception("memory compaction failed during /reset")
    context_store.clear()
    with suppress(TelegramBadRequest):
        await status.edit_text("✅ Контекст очищен. Память обновлена.")


# ─────────────────────────────────────────────────────────────────────
# /randomreply — включить/выключить случайные ответы на любые сообщения
# ─────────────────────────────────────────────────────────────────────
@router.message(Command("randomreply"))
async def cmd_randomreply(message: Message, command: CommandObject) -> None:
    current = features.is_random_reply_enabled()
    arg = (command.args or "").strip().lower() if command.args else ""
    if arg in ("on", "1", "вкл", "да", "true", "yes"):
        new_state = True
    elif arg in ("off", "0", "выкл", "нет", "false", "no"):
        new_state = False
    else:
        # Без аргумента — инвертируем текущее состояние
        new_state = not current

    if new_state == current:
        state_text = "включены ✅" if new_state else "выключены ❌"
        with suppress(TelegramBadRequest):
            await message.answer(
                f"🎲 Случайные ответы уже {state_text}.\n"
                f"Вероятность срабатывания: {settings.random_reply_chance:.1%}."
            )
        return

    features.set_random_reply_enabled(new_state)
    state_text = "включены ✅" if new_state else "выключены ❌"
    with suppress(TelegramBadRequest):
        await message.answer(
            f"🎲 Случайные ответы теперь {state_text}.\n"
            f"Вероятность срабатывания: {settings.random_reply_chance:.1%}."
        )


# ─────────────────────────────────────────────────────────────────────
# /summary — сводка за вчера
# ─────────────────────────────────────────────────────────────────────
@router.message(Command("summary"))
async def cmd_summary(message: Message, command: CommandObject) -> None:
    tz = ZoneInfo(settings.timezone)
    today = _dt.datetime.now(tz=tz).date()
    # Опциональный аргумент — дата в формате YYYY-MM-DD; по умолчанию вчера
    target_date = today - _dt.timedelta(days=1)
    if command.args and command.args.strip():
        try:
            target_date = _dt.date.fromisoformat(command.args.strip())
        except ValueError:
            with suppress(TelegramBadRequest):
                await message.answer(
                    "Не понял дату. Используй формат YYYY-MM-DD или /summary без аргумента."
                )
            return

    date_str = target_date.isoformat()
    status = await message.answer(f"⏳ Собираю сводку за {date_str}…")

    msgs = history.read_day(date_str)
    if not msgs:
        with suppress(TelegramBadRequest):
            await status.edit_text(f"За {date_str} сообщений не было.")
        return

    lock = await _get_user_lock(message.from_user.id)
    async with lock:
        try:
            summary = await engine.summarize_day(msgs, date_str)
        except Exception as e:
            log.exception("summary generation failed")
            with suppress(TelegramBadRequest):
                await status.edit_text(f"{prompts.ERROR_PREFIX}\n\n{e}")
            return

    summary = summary.strip()
    if not summary:
        summary = "(не удалось сгенерировать сводку — модель не успела за лимит токенов)"
    await _edit_or_reply(status, summary)

    # Кешируем готовую сводку
    try:
        settings.summaries_dir.mkdir(parents=True, exist_ok=True)
        (settings.summaries_dir / f"{date_str}.json").write_text(
            summary, encoding="utf-8"
        )
    except Exception:
        log.exception("failed to cache summary")


# ─────────────────────────────────────────────────────────────────────
# Главный текстовый хендлер — срабатывает на упоминание/фразу/reply
# ─────────────────────────────────────────────────────────────────────
@router.message(F.text)
async def on_text(message: Message, bot: Bot) -> None:
    bot_user_id = bot.id if bot else None
    if not triggers.should_reply(message, bot_user_id):
        return

    user_query = triggers.strip_trigger(message.text or "")
    if not user_query:
        return  # триггер без полезного текста — игнор

    if message.from_user:
        username = (
            message.from_user.username
            or message.from_user.first_name
            or str(message.from_user.id)
        )
        first_name = message.from_user.first_name or ""
    else:
        username = "?"
        first_name = ""

    status = await message.answer("⏳ Думаю…")

    # TTL-очистка контекста: компактим в фон, не блокируем ответ
    try:
        if context_store.is_expired() and context_store.get_message_count() > 0:
            dialog = context_store.get_messages_for_llm()
            context_store.clear()
            asyncio.create_task(_compact_memory_background(dialog))
    except Exception:
        log.exception("TTL check failed; clearing context anyway")
        context_store.clear()

    # Добавляем пользовательский запрос в контекст
    context_store.append_user_message(
        message.chat.id, username, user_query, first_name=first_name
    )
    context_store.touch(message.chat.id)

    # Последние сообщения группы — чтобы модель видела контекст беседы
    recent = history.read_recent(settings.history_window)

    # Собираем сообщения для LLM: system + history из контекста
    system_prompt = prompts.build_system_prompt(recent_history=recent)
    llm_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    llm_messages.extend(context_store.get_messages_for_llm())

    lock = await _get_user_lock(message.from_user.id)
    async with lock:
        try:
            answer = await engine.chat(llm_messages, use_tools=True)
        except Exception as e:
            log.exception("chat generation failed")
            with suppress(TelegramBadRequest):
                await status.edit_text(f"{prompts.ERROR_PREFIX}\n\n{e}")
            return

    answer = answer.strip()
    if not answer:
        answer = (
            "(не удалось сгенерировать ответ — модель не уложилась в лимит токенов. "
            "Попробуй переформулировать или разбить на части.)"
        )

    # Сохраняем ответ в контексте и обновляем метку времени
    context_store.append_assistant_message(answer)
    context_store.touch(message.chat.id)

    await _edit_or_reply(status, answer)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────
async def _maybe_compact_memory() -> None:
    """Сжать текущий контекст в memory.json. Используется в /reset."""
    dialog = context_store.get_messages_for_llm()
    if not dialog:
        return
    previous_memory = memory.to_prompt_block()
    compacted = await engine.compact_dialog_for_memory(dialog, previous_memory)
    compacted = compacted.strip()
    if compacted:
        memory.update_summary(compacted)


async def _compact_memory_background(dialog: list[dict[str, str]]) -> None:
    """Фоновая компакция контекста в память. Не блокирует ответ пользователю."""
    try:
        if not dialog:
            return
        previous_memory = memory.to_prompt_block()
        compacted = await engine.compact_dialog_for_memory(dialog, previous_memory)
        compacted = compacted.strip()
        if compacted:
            memory.update_summary(compacted)
            log.info("background memory compaction done")
    except Exception:
        log.exception("background memory compaction failed")


async def _edit_or_reply(status: Message, text: str) -> None:
    """Заменить плейсхолдер на ответ. Если текст длиннее 4096 — обрезать.

    Перед отправкой убирается markdown-разметка — Telegram получает plain text.
    """
    text = _strip_markdown(text)
    MAX_LEN = 4096
    if len(text) > MAX_LEN:
        text = text[: MAX_LEN - 1].rstrip() + "…"
    with suppress(TelegramBadRequest):
        await status.edit_text(text)
        return
    # Если edit не удался (например, текст не изменился) — пробуем reply
    with suppress(TelegramBadRequest):
        await status.reply(text)
