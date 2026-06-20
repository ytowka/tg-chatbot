"""История сообщений группы. Append-only JSONL-файлы, по одному на день.

Имя файла: YYYY-MM-DD.jsonl, дата считается в настроенной таймзоне.
Каждая строка — JSON-объект сообщения.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from config import settings


def _ensure_dir() -> None:
    settings.messages_dir.mkdir(parents=True, exist_ok=True)


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def _file_for_ts(ts: float) -> Path:
    dt = datetime.fromtimestamp(ts, tz=_tz())
    return settings.messages_dir / f"{dt.strftime('%Y-%m-%d')}.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return result


def append(message: dict[str, Any]) -> None:
    """Дописать сообщение в сегодняшний файл.

    Ожидаемые ключи: ts (float), text (str), user_id, username, first_name,
    chat_id, message_id, is_bot_mention, is_reply_to_bot.
    """
    _ensure_dir()
    path = _file_for_ts(float(message["ts"]))
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")


def read_day(date_str: str) -> list[dict[str, Any]]:
    """Все сообщения за указанный день (формат YYYY-MM-DD)."""
    path = settings.messages_dir / f"{date_str}.jsonl"
    return _read_jsonl(path)


def read_between(start_ts: float, end_ts: float) -> list[dict[str, Any]]:
    """Сообщения за интервал [start_ts, end_ts), с фильтром по ts."""
    tz = _tz()
    start_date = datetime.fromtimestamp(start_ts, tz=tz).date()
    end_date = datetime.fromtimestamp(end_ts, tz=tz).date()
    out: list[dict[str, Any]] = []
    current = start_date
    while current <= end_date:
        path = settings.messages_dir / f"{current.strftime('%Y-%m-%d')}.jsonl"
        out.extend(_read_jsonl(path))
        current += timedelta(days=1)
    return [m for m in out if start_ts <= float(m.get("ts", 0)) < end_ts]


def read_recent(n: int) -> list[dict[str, Any]]:
    """Последние N сообщений (хронологический порядок)."""
    files = sorted(settings.messages_dir.glob("*.jsonl"))
    out: list[dict[str, Any]] = []
    for path in reversed(files):
        msgs = _read_jsonl(path)
        out = msgs + out
        if len(out) >= n:
            break
    return out[-n:] if len(out) > n else out


def search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Простой substring-поиск (case-insensitive) по всей истории.

    Возвращает в хронологическом порядке. Без эмбеддингов/BM25 — MVP.
    """
    needle = query.strip().lower()
    if not needle:
        return []
    matches: list[dict[str, Any]] = []
    for path in sorted(settings.messages_dir.glob("*.jsonl")):
        for msg in _read_jsonl(path):
            text = str(msg.get("text", "")).lower()
            if needle in text:
                matches.append(msg)
    matches.sort(key=lambda m: float(m.get("ts", 0)))
    return matches[-limit:] if len(matches) > limit else matches


def iter_all() -> Iterable[dict[str, Any]]:
    """Итератор по всем сообщениям (хронологически). Для тестов/дебага."""
    for path in sorted(settings.messages_dir.glob("*.jsonl")):
        yield from _read_jsonl(path)


def now_ts() -> float:
    return datetime.now(tz=timezone.utc).timestamp()
