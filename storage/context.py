"""Контекст диалога: последние сообщения группы + метка времени.

Хранится в data/context.json. TTL = settings.context_ttl_hours (по умолчанию 6).
Если с последнего обращения к боту прошло больше TTL — контекст считается
устаревшим и должен быть очищен (после обновления памяти).
"""
from __future__ import annotations

import json
import time
from typing import Any

from config import settings


def _default() -> dict[str, Any]:
    return {"chat_id": None, "last_interaction_at": 0.0, "messages": []}


def load() -> dict[str, Any]:
    if not settings.context_file.exists():
        return _default()
    try:
        data = json.loads(settings.context_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default()
    base = _default()
    base.update(data)
    return base


def save(data: dict[str, Any]) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    tmp = settings.context_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(settings.context_file)


def touch(chat_id: int) -> None:
    ctx = load()
    ctx["chat_id"] = chat_id
    ctx["last_interaction_at"] = time.time()
    save(ctx)


def append_user_message(
    chat_id: int, username: str, content: str, first_name: str = ""
) -> None:
    ctx = load()
    ctx["chat_id"] = chat_id
    ctx["last_interaction_at"] = time.time()
    ctx["messages"].append(
        {
            "role": "user",
            "content": f"@{username}: {content}",
            "ts": time.time(),
            "username": username,
            "first_name": first_name,
        }
    )
    save(ctx)


def append_assistant_message(content: str) -> None:
    ctx = load()
    ctx["messages"].append(
        {"role": "assistant", "content": content, "ts": time.time()}
    )
    save(ctx)


def is_expired() -> bool:
    ctx = load()
    last = float(ctx.get("last_interaction_at") or 0)
    if not last:
        return False
    age = time.time() - last
    return age > settings.context_ttl_hours * 3600


def clear() -> None:
    """Очистить сообщения, сохраняя chat_id."""
    ctx = load()
    save({"chat_id": ctx.get("chat_id"), "last_interaction_at": 0.0, "messages": []})


def get_messages_for_llm() -> list[dict[str, str]]:
    """Вернуть сообщения в формате {role, content}, готовом для chat_completion."""
    ctx = load()
    return [
        {"role": m["role"], "content": m["content"]} for m in ctx.get("messages", [])
    ]


def get_message_count() -> int:
    return len(load().get("messages", []))
