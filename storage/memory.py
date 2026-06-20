"""Память бота: компактная сводка прошлых бесед, факты об участниках.

Хранится в data/memory.json. Обновляется перед очисткой контекста
(по TTL или /reset): модель делает compact summary текущего контекста,
результат сливается в это файл.
"""
from __future__ import annotations

import json
import time
from typing import Any

from config import settings


def _default() -> dict[str, Any]:
    return {
        "updated_at": 0.0,
        "summary": "",
        "participants": {},
        "topics": [],
        "facts": [],
    }


def load() -> dict[str, Any]:
    if not settings.memory_file.exists():
        return _default()
    try:
        data = json.loads(settings.memory_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default()
    base = _default()
    base.update(data)
    if not isinstance(base.get("participants"), dict):
        base["participants"] = {}
    return base


def save(data: dict[str, Any]) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = time.time()
    tmp = settings.memory_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(settings.memory_file)


def get_user_info(username: str) -> dict[str, Any] | None:
    """Найти участника по username (case-insensitive, с/без @)."""
    key = username.lower().lstrip("@")
    for uname, info in load().get("participants", {}).items():
        if uname.lower().lstrip("@") == key:
            return info
    return None


def update_summary(new_summary: str) -> None:
    """Заменить summary (используется после TTL/reset)."""
    data = load()
    data["summary"] = new_summary.strip()
    save(data)


def add_note(text: str, category: str = "fact", username: str = "") -> str:
    """Добавить факт в память. Вызывается tool-ом save_memory.

    Категории:
      user_info — факт о пользователе (требуется username)
      topic     — обсуждённая тема
      decision  — принятое решение
      promise   — обещание/обязательство
      fact      — прочий факт (по умолчанию)

    Возвращает подтверждение для модели.
    """
    text = text.strip()
    if not text:
        return "Пустая заметка — проигнорировано."
    data = load()

    if category == "user_info" and username:
        uname = username.lower().lstrip("@")
        entry = data["participants"].setdefault(
            uname, {"facts": "", "first_name": ""}
        )
        existing = (entry.get("facts") or "").strip()
        entry["facts"] = (existing + "\n" + text).strip() if existing else text
    elif category == "topic":
        if text not in data["topics"]:
            data["topics"].append(text)
    else:
        tag = category if category in ("decision", "promise") else "fact"
        data["facts"].append(f"[{tag}] {text}")

    save(data)
    return f"Сохранено в память ({category}): {text}"


def to_prompt_block() -> str:
    """Сформировать текстовый блок для вставки в system prompt.

    Возвращает пустую строку, если памяти ещё нет.
    """
    data = load()
    parts: list[str] = []

    summary = (data.get("summary") or "").strip()
    if summary:
        parts.append(f"Краткая сводка прошлых бесед:\n{summary}")

    participants = data.get("participants", {})
    if participants:
        lines = []
        for uname, info in participants.items():
            facts = (info.get("facts") or "").strip()
            if facts:
                lines.append(f"- @{uname}: {facts}")
        if lines:
            parts.append("Что известно об участниках:\n" + "\n".join(lines))

    topics = data.get("topics") or []
    if topics:
        parts.append("Ранее обсуждавшиеся темы: " + ", ".join(topics))

    facts = data.get("facts") or []
    if facts:
        parts.append("Ключевые факты:\n- " + "\n- ".join(facts))

    return "\n\n".join(parts) if parts else ""
