"""Определения tools и диспетчер для tool calling."""
from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from typing import Any

from storage import history, memory

log = logging.getLogger(__name__)


_HERMES_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*<function=(\w+)>(.*?)</function>\s*</tool_call>",
    re.DOTALL,
)
_HERMES_PARAM_RE = re.compile(
    r"<parameter=(\w+)>(.*?)</parameter>",
    re.DOTALL,
)


def parse_hermes_tool_calls(content: str) -> list[dict[str, Any]]:
    """Распарсить Hermes-style tool calls из content модели.

    Формат (HauhauCS/Aggressive finetune и др.):
        <tool_call>
        <function=func_name>
        <parameter=name>value</parameter>
        </function>
        </tool_call>

    Возвращает список в OpenAI-совместимом виде:
        {id, type='function', function: {name, arguments(JSON string)}}
    """
    calls: list[dict[str, Any]] = []
    for idx, match in enumerate(_HERMES_TOOL_CALL_RE.finditer(content)):
        func_name = match.group(1).strip()
        body = match.group(2)
        args: dict[str, Any] = {}
        for pm in _HERMES_PARAM_RE.finditer(body):
            pname = pm.group(1).strip()
            pvalue = pm.group(2).strip()
            try:
                args[pname] = json.loads(pvalue)
            except json.JSONDecodeError:
                args[pname] = pvalue
        calls.append(
            {
                "id": f"hermes_call_{idx}",
                "type": "function",
                "function": {
                    "name": func_name,
                    "arguments": args,
                },
            }
        )
    return calls


def strip_tool_call_blocks(content: str) -> str:
    """Удалить <tool_call>...</tool_call> блоки из текста (для чистоты истории)."""
    return _HERMES_TOOL_CALL_RE.sub("", content).strip()


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_history",
            "description": (
                "Искать сообщения в истории чата по ключевым словам. "
                "Используй, когда нужен факт из прошлых бесед."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Ключевые слова для поиска",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Максимальное число результатов (по умолчанию 10)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_messages_between",
            "description": (
                "Получить все сообщения из истории за период. "
                "Формат дат — ISO 8601 (например, 2026-06-19T00:00:00)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {
                        "type": "string",
                        "description": "ISO 8601 дата/время начала (включительно)",
                    },
                    "end": {
                        "type": "string",
                        "description": "ISO 8601 дата/время конца (исключительно)",
                    },
                },
                "required": ["start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_info",
            "description": (
                "Получить известные факты об участнике группы по его @username."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Telegram username участника",
                    },
                },
                "required": ["username"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": (
                "Сохранить важный факт в долгосрочную память бота. "
                "Используй, когда участник сообщает что-то достойное запоминания: "
                "профессия, роль, дедлайн, решение, обещание, важный факт. "
                "Не сохраняй мелочи и бытовые сообщения."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Что запомнить (кратко, по-русски)",
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "user_info",
                            "topic",
                            "decision",
                            "promise",
                            "fact",
                        ],
                        "description": (
                            "Категория заметки: "
                            "user_info — факт о пользователе (нужен username), "
                            "topic — обсуждённая тема, "
                            "decision — принятое решение, "
                            "promise — обещание/обязательство, "
                            "fact — прочий факт"
                        ),
                    },
                    "username": {
                        "type": "string",
                        "description": (
                            "Username участника (обязательно для category=user_info)"
                        ),
                    },
                },
                "required": ["text", "category"],
            },
        },
    },
]


def _parse_iso(s: str) -> float:
    """ISO 8601 → unix ts. Допускает 'YYYY-MM-DD' или 'YYYY-MM-DDTHH:MM:SS'."""
    s = s.strip()
    try:
        if "T" not in s:
            s = s + "T00:00:00"
        dt = _dt.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            from zoneinfo import ZoneInfo

            from config import settings

            dt = dt.replace(tzinfo=ZoneInfo(settings.timezone))
        return dt.timestamp()
    except ValueError as e:
        raise ValueError(f"Не удалось распарсить дату '{s}': {e}")


def _format_messages(msgs: list[dict[str, Any]]) -> str:
    if not msgs:
        return ""
    lines = []
    for m in msgs:
        ts = float(m.get("ts") or 0)
        hhmm = _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        uname = m.get("username") or m.get("first_name") or "?"
        text = (m.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"[{hhmm}] @{uname}: {text}")
    return "\n".join(lines)


def dispatch_tool(name: str, arguments: dict[str, Any]) -> str:
    """Выполнить tool по имени. Возвращает строку-результат для LLM."""
    log.info("tool call: %s(%s)", name, arguments)
    if name == "search_history":
        query = str(arguments.get("query", "")).strip()
        limit = int(arguments.get("limit", 10) or 10)
        if not query:
            return "Ошибка: пустой запрос."
        result = history.search(query, limit=max(1, min(limit, 50)))
        out = _format_messages(result)
        return out or "Ничего не найдено по этому запросу."

    if name == "get_messages_between":
        try:
            start = _parse_iso(str(arguments.get("start", "")))
            end = _parse_iso(str(arguments.get("end", "")))
        except ValueError as e:
            return f"Ошибка: {e}"
        if end <= start:
            return "Ошибка: end должен быть больше start."
        result = history.read_between(start, end)
        out = _format_messages(result)
        return out or "За указанный период сообщений не было."

    if name == "get_user_info":
        username = str(arguments.get("username", "")).strip().lstrip("@")
        if not username:
            return "Ошибка: не указан username."
        info = memory.get_user_info(username)
        if not info:
            return f"Об участнике @{username} ничего не известно."
        return json.dumps(info, ensure_ascii=False, indent=2)

    if name == "save_memory":
        text = str(arguments.get("text", "")).strip()
        category = str(arguments.get("category", "fact")).strip()
        username = str(arguments.get("username", "")).strip()
        if not text:
            return "Ошибка: пустой текст заметки."
        return memory.add_note(text, category, username)

    return f"Ошибка: неизвестный инструмент '{name}'."
