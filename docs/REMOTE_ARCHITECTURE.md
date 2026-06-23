# Удалённая архитектура: сервер вне РФ + LLM на ноутбуке

Telegram заблокирован в РФ. Решение: бот крутится на сервере вне РФ
(доступ к Telegram API), а вычисления LLM выполняются на ноутбуке через
SSH reverse tunnel.

## Схема

```
┌──────────────────────────┐          ┌─────────────────────────────────┐
│  Сервер (вне РФ, VPS)    │          │  Ноутбук (РФ, macOS/Apple Si)   │
│                          │          │                                 │
│  python main.py          │          │  llama-server (Qwen3.5-9B)      │
│  ├─ aiogram → Telegram ✓ │          │  :127.0.0.1:8081/v1             │
│  └─ AsyncOpenAI клиент   │◄────────┤  (OpenAI-совместимый API)       │
│       POST localhost:8081│  SSH     │                                 │
│       /v1/chat/completions│ reverse │  ssh -R 8081:localhost:8081     │
│                          │  tunnel  │  └─ проброс от ноута к серверу  │
└──────────────────────────┘          └─────────────────────────────────┘
```

SSH reverse tunnel: ноутбук сам инициирует подключение к серверу и
пробрасывает свой порт 8081 на localhost сервера. Сервер обращается к
`localhost:8081` — это туннель к ноуту. NAT обходится, т.к. инициатор —
ноут.

## Переключатель режимов

- `LLM_MODE=local` — запросы идут на `LLM_BASE_URL` (llama-server на
  ноуте через туннель).
- `LLM_MODE=api` — (зарезервировано) запросы идут на облачный API.

Оба режима используют единый OpenAI-совместимый HTTP-клиент (`AsyncOpenAI`),
отличается только `base_url`.

## Изменённые файлы

| Файл | Действие |
|---|---|
| `models/launch3.5-server.sh` | **НОВЫЙ** — запуск Qwen3.5-9B как llama-server |
| `config.py` | Убрать `model_path`, `n_gpu_layers`, `n_ctx`. Добавить `llm_*` поля |
| `llm/engine.py` | `llama_cpp.Llama` → `openai.AsyncOpenAI`. Удалить `_disable_thinking()` |
| `main.py` | Health-check (`GET /v1/models`) вместо preload модели |
| `requirements.txt` | `llama-cpp-python` → `openai` |
| `.env.example` | Новые `LLM_*` переменные |
| `docs/DEPLOY.md` | Инструкция деплоя + SSH tunnel |

Не изменились: `bot/handlers.py`, `bot/triggers.py`, `bot/middleware.py`,
`llm/tools.py`, `llm/prompts.py`, `storage/*`.

## Риски

1. **`repeat_penalty` через `extra_body`** — llama-server поддерживает
   кастомные поля. Если версия старая и игнорирует — падение качества
   минимально.
2. **Туннель падает** — `autossh` переподключает автоматически. Бот
   получает ошибку от LLM, пишет её в чат.
3. **Ноут уснул** — бот выдает ошибку `Connection refused`. Будущий
   `api`-режим решит это.
