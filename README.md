# Чат-бот с локальной LLM для Telegram-группы

Ассистент для Telegram-группы на локальной LLM через `llama-cpp-python` (Metal).
Назначение — универсальный ассистент, отвечающий в группе по упоминанию/фразе/reply,
с накоплением истории диалога, контекстом с TTL, файлом памяти и сводкой за день.

Полное описание архитектуры и решений — в [`docs/PLAN.md`](docs/PLAN.md).
Функциональные требования — в [`docs/requirements.md`](docs/requirements.md).

## Возможности

- Отвечает на сообщения с **настраиваемой фразой** (по умолчанию `сильвер`),
  **@mention** бота, или **reply** на сообщение бота.
- Контекст диалога с TTL **6 часов** без обращений к боту → автоочистка с
  предварительной компрессией в долгосрочную память.
- Долгосрочная **память бота** (`data/memory.json`): факты, участники, темы.
- **История всех сообщений группы** в `data/messages/YYYY-MM-DD.jsonl`.
- **Tool calling**: модель может искать по истории, фильтровать по датам,
  запрашивать факты об участниках.
- `/summary [YYYY-MM-DD]` — сводка за день (по умолчанию вчера).
- `/reset` — принудительная очистка контекста (доступна всем).
- Полностью локальный инференс на Apple Silicon (Metal).

## Требования

- macOS на Apple Silicon, от 16 ГБ RAM (32+ рекомендуется для 9B+ моделей).
- Python 3.11+ (тестировалось на 3.13).
- Файл GGUF-модели в `models/`.

## Установка

### 1. Создать venv и установить зависимости

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Установить `llama-cpp-python` с поддержкой Metal

Эту библиотеку **нельзя** ставить из `requirements.txt` — для Metal нужна отдельная
сборка из исходников:

```bash
CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python --upgrade --force-reinstall --no-cache-dir
```

Проверка, что Metal подключён (должны увидеть `libggml-metal.dylib`):

```bash
python -c "import llama_cpp, os; print([f for f in os.listdir(os.path.dirname(llama_cpp.__file__)+'/lib') if 'metal' in f])"
```

### 3. Положить модель

Скачать GGUF-модель и положить в `models/`. По умолчанию ожидается
`models/Qwen3.5-9B-Q6_K.gguf`. Имя файла можно поменять через `MODEL_PATH` в `.env`.

### 4. Создать Telegram-бота

1. Через [@BotFather](https://t.me/BotFather) создайте бота и получите токен.
2. В настройках бота у BotFather **отключите Group Privacy**:
   `Bot Settings → Group Privacy → Turn off`. Это нужно, чтобы бот видел все
   сообщения группы (для истории и сводки).
3. Узнайте `username` бота (без `@`).
4. Добавьте бота в группу.

### 5. Создать `.env`

```bash
cp .env.example .env
```

Заполните:

```dotenv
BOT_TOKEN=...                   # токен от BotFather
BOT_USERNAME=my_chat_bot        # без @
TRIGGER_PHRASE=сильвер          # текстовая фраза для отклика
CONTEXT_TTL_HOURS=6
TIMEZONE=Europe/Moscow
MODEL_PATH=models/Qwen3.5-9B-Q6_K.gguf
```

## Запуск

```bash
source .venv/bin/activate
python main.py
```

При первом запуске бот загрузит модель в память (~10-20 секунд для 9B),
после чего начнёт слушать апдейты.

## Структура runtime-данных

```
data/
├── messages/
│   └── 2026-06-20.jsonl    # все сообщения группы за день
├── context.json            # активный контекст + метка последнего обращения
├── memory.json             # компактная сводка прошлых бесед
└── summaries/
    └── 2026-06-19.json     # кешированные сводки по дням
```

## Команды бота

| Команда | Описание |
|---|---|
| `/start` | Приветствие и список команд. |
| `/reset` | Очистить контекст (с обновлением памяти). Доступна всем. |
| `/summary [YYYY-MM-DD]` | Сводка сообщений за день (по умолчанию вчера). |

## Ограничения безопасности

- Бот **не должен быть администратором** группы (см. `docs/requirements.md`).
- В коде отсутствуют вызовы `deleteMessage`, `kickChatMember`,
  `restrictChatMember` и подобных. Системный промпт явно запрещает выдавать
  инструкции по модерации.

## Известные особенности текущей модели

- `Qwen3.5-9B-Uncensored-HauhauCS-Aggressive` использует **thinking mode**:
  перед финальным ответом генерирует `<think>...</think>` блок. Движок
  автоматически剥离 thinking и отдаёт только финальный ответ.
- Thinking отъедает много токенов, поэтому `max_tokens=2048` для основного
  чата и до `4096` для компрессии памяти. Если ответ пустой — модель не успела
  закрыть thinking за лимит; попросите её переформулировать короче.
- Tool calling реализован через **Hermes-style** формат (модель отдаёт
  `<tool_call>...</tool_call>` в content), парсер встроен в `llm/tools.py`.
