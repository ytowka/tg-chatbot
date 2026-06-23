"""Feature toggles: runtime-флаги, переключаемые командами бота.

Хранится в data/features.json. По умолчанию все флаги выключены.
Используется, например, для случайных ответов (/randomreply).
"""
from __future__ import annotations

import json
import time
from typing import Any

from config import settings


def _default() -> dict[str, Any]:
    return {
        "updated_at": 0.0,
        "random_reply_enabled": False,
    }


def load() -> dict[str, Any]:
    if not settings.features_file.exists():
        return _default()
    try:
        data = json.loads(settings.features_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default()
    base = _default()
    base.update(data)
    return base


def save(data: dict[str, Any]) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = time.time()
    tmp = settings.features_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(settings.features_file)


def is_random_reply_enabled() -> bool:
    return bool(load().get("random_reply_enabled", False))


def set_random_reply_enabled(enabled: bool) -> bool:
    """Установить флаг случайных ответов. Возвращает новое значение."""
    data = load()
    data["random_reply_enabled"] = bool(enabled)
    save(data)
    return bool(enabled)
