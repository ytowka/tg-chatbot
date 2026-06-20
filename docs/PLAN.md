# План реализации Telegram-бота с локальной LLM (v2 — групповой бот)

> v2 учитывает требования из `docs/requirements.md`. Это уже не ЛС-бот, а
> групповой бот с историей сообщений, контекстом с TTL, поиском по истории,
> файлом памяти и сводкой дня.

## Стек

| Компонент | Выбор |
|---|---|
| Python | 3.13 |
| Telegram | `aiogram>=3.4` (privacy mode **off** у @BotFather) |
| LLM | `llama-cpp-python` (Metal), Qwen3.5-9B Q6_K |
| Конфиг | `pydantic-settings`, `python-dotenv` |
| Хранилище | JSON/JSONL-файлы (MVP — одна группа) |

## Технические вводные
- **Железо:** Mac на Apple Silicon, **48 ГБ RAM** → комфортно для dense-моделей до ~30B.
- **Модель:** Qwen3.5-9B (dense) в квантизации **Q6_K** (~6.9 ГБ GGUF). Файл: `models/Qwen3.5-9B-Q6_K.gguf`.
- **LLM-инференс:** `llama-cpp-python` с Metal-сборкой (`GGML_METAL=on`).
- **Стриминг:** без стриминга, ответ одним сообщением (через edit плейсхолдера).

### Почему `llama-cpp-python`, а не Ollama/LM Studio
- Прямой контроль над параметрами генерации и загрузки слоёв на GPU.
- Не требует отдельного демона — всё в одном процессе.
- Поддержка tool calling из коробки.

## Бизнес-логика

### Триггеры ответа (бот отвечает если выполнено любое)
- **Текстовая фраза** «сильвер» (case-insensitive, из `.env`).
- **Нативное @mention** (Telegram username бота).
- **Reply** на любое сообщение бота.

Все остальные сообщения — **только пишем в history**, не отвечаем.

### Команды
- `/start` — приветствие.
- `/reset` — принудительная очистка контекста (доступна всем). Перед очисткой обновляем `memory.json`.
- `/summary` — сводка сообщений за вчера (по локальному TZ из `.env`).

### Контекст
- TTL = **6 часов** без обращения к боту (не без любой активности в группе).
- При истечении → контекст очищается, `memory.json` обновляется (моделью).
- Что лежит в контексте для обычного вопроса: последние ~20 сообщений + текущий запрос + системный промпт + блок памяти.

### Поиск по истории (гибрид)
- **Rule-based (по умолчанию):** при вопросе отдаём последние N сообщений; `/summary` тянет сообщения за сутки через прямой фильтр по timestamp.
- **Tool calling (Qwen3.6):** модель может дополнительно вызвать:
  - `search_history(query, limit)` — keyword-поиск (без embeddings в MVP, BM25/substring).
  - `get_messages_between(start, end)` — выборка по датам.
  - `get_user_info(username)` — факты из `memory.json`.

### Файлы состояния (`storage/`)
```
storage/
├── messages/                 # JSONL по дням — удобно для сводки и TTL
│   └── 2026-06-20.jsonl
├── context.json              # активный контекст + last_interaction_at
├── memory.json               # компактная память бота (факты, участники, темы)
└── summaries/
    └── 2026-06-19.json       # кеш готовых сводок
```

### Safety
- Бот **не админ** группы (рекомендация в README).
- В коде отсутствуют вызовы `deleteMessage`, `kickChatMember`, `restrictChatMember` и т.п.
- Системный промпт запрещает боту выдавать инструкции «удалить/забанить» и подобное.

### Язык, тон и UX
- **Язык ответов:** всегда русский (жёстко в system prompt, независимо от языка запроса).
- **Длина ответа:** `max_tokens=1024`, `temperature=0.7`.
- **UX при генерации:** pattern «placeholder + edit»:
  1. На входящий триггерный сообщение сразу отвечаем сообщением-плейсхолдером «⏳ Думаю…», получаем `message_id`.
  2. Запускаем генерацию в `asyncio.to_thread(...)`.
  3. По готовности — `edit_message_text` заменяет плейсхолдер на ответ модели.
  4. При ошибке — `edit_message_text` с деталями ошибки (плюс запись в лог).

### Краевые случаи
- **Длинный ответ:** при превышении 4096 символов обрезаем по лимиту Telegram.
- **Параллельные запросы от одного пользователя:** per-user очередь (`asyncio.Lock` по `user_id`).

## Структура проекта
```
chat-bot/
├── docs/
│   ├── PLAN.md
│   └── requirements.md
├── storage/                # runtime-данные, в .gitignore
├── models/
│   └── Qwen3.5-9B-Q6_K.gguf
├── bot/
│   ├── __init__.py
│   ├── handlers.py         # /start, /reset, /summary, текстовый триггер
│   ├── triggers.py         # определение, нужно ли отвечать
│   └── middleware.py       # запись всех входящих в history + TTL-проверка
├── llm/
│   ├── __init__.py
│   ├── engine.py           # Llama() синглтон, generate(), tool-calling loop
│   ├── tools.py            # search_history, get_messages_between, get_user_info
│   └── prompts.py          # system prompt, шаблоны сводки/памяти
├── storage/
│   ├── __init__.py
│   ├── history.py          # append/чтение messages/*.jsonl
│   ├── context.py          # контекст + TTL (6ч)
│   └── memory.py           # чтение/запись/обновление memory.json
├── config.py
├── main.py
├── .env.example
├── .gitignore
└── requirements.txt
```

## Ключевые параметры модели
- `n_gpu_layers=-1` — все слои на Metal.
- `n_ctx=8192` — стартовый контекст, расширяемо.
- `max_tokens=1024`, `temperature=0.7`.
- `create_chat_completion` (Qwen3.6 применяет chat template автоматически).

## Критическое техническое замечание

Генерация в `llama-cpp-python` **блокирующая**. Обязательно оборачивать вызов в `asyncio.to_thread()`, иначе aiogram event loop зависнет на время ответа.

## Шаги реализации
1. Установить `llama-cpp-python` с Metal:
   ```bash
   CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python --upgrade --force-reinstall --no-cache-dir
   ```
2. Установить остальные зависимости:
   ```bash
   pip install aiogram pydantic-settings python-dotenv
   ```
3. ~~Скачать модель.~~ ✓ Готово: `models/Qwen3.5-9B-Q6_K.gguf` (6.9 ГБ).
4. Реализовать `config.py` (поля: trigger, ttl_hours, tz, paths, telegram_token, model params).
5. Реализовать `storage/` (history, context, memory) — без LLM.
6. Реализовать `llm/engine.py` + `llm/prompts.py` — генерация и базовый промпт.
7. Реализовать `bot/middleware.py` — запись history + проверка TTL.
8. Реализовать `bot/triggers.py` — определение отвечать или нет.
9. Реализовать `bot/handlers.py` — `/start`, `/reset`, `/summary`, текстовый триггер.
10. Добавить `llm/tools.py` — tool definitions + диспетчер.
11. Связать tool calling в `engine.py`.
12. Создать `.env.example`, `.gitignore`, README с инструкцией по privacy mode.

## Что НЕ входит в MVP
- Поддержка нескольких групп.
- Embeddings/семантический поиск (только keyword/BM25/substring).
- Стриминг ответов.
- Авто-сводка по расписанию (только по команде).
- Обработка медиа (только текст).
- Ротация/архивация старой истории.
- Rate-limit, админка, логирование в БД.
