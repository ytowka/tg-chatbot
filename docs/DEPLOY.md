# Деплой: сервер вне РФ + LLM на ноутбуке

## 1. Ноутбук (РФ) — поднятие llama-server

### Установка llama.cpp (если ещё не собран)

```sh
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
cmake -B build -DGGML_METAL=ON
cmake --build build --config Release
# бинарник: build/bin/llama-server
```

### Запуск

```sh
cd /Users/danil/PycharmProjects/chat-bot/models
bash launch3.5-server.sh
```

Проверка: `curl http://127.0.0.1:8081/v1/models` → должен вернуть `qwen3.5-9b`.

## 2. SSH reverse tunnel (ноут → сервер)

Ноутбук пробрасывает свой порт 8081 на localhost сервера. Инициатор —
ноут, поэтому NAT не проблема.

### Установка autossh

```sh
brew install autossh
```

### Команда

```sh
autossh -M 0 -N \
  -o "ServerAliveInterval 30" \
  -o "ServerAliveCountMax 3" \
  -o "ExitOnForwardFailure yes" \
  -R 8081:localhost:8081 \
  user@SERVER_IP
```

На сервере нужно:
- SSH-доступ по ключу (без пароля — для autossh).
- В `/etc/ssh/sshd_config`: `GatewayPorts no` (по умолчанию) — туннель
  доступен только на localhost сервера, что нам и нужно.

### Проверка туннеля (на сервере)

```sh
curl http://127.0.0.1:8081/v1/models
```

## 3. Сервер (вне РФ) — деплой бота в Docker

### Установка Docker

```sh
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER  # затем re-login
```

### Клонирование и настройка

```sh
git clone <repo_url> chat-bot && cd chat-bot
```

Создать `.env` на сервере:

```env
BOT_TOKEN=<от @BotFather>
BOT_USERNAME=<username_бота>

LLM_MODE=local
LLM_BASE_URL=http://127.0.0.1:8081/v1
LLM_MODEL=qwen3.5-9b
LLM_API_KEY=not-needed
LLM_REQUEST_TIMEOUT=120

MAX_TOKENS=2048
TEMPERATURE=0.4
TOP_P=0.9
REPEAT_PENALTY=1.15

TRIGGER_PHRASE=Цветочный лох
CONTEXT_TTL_HOURS=6
HISTORY_WINDOW=15
TIMEZONE=Europe/Moscow
```

> `LLM_BASE_URL=http://127.0.0.1:8081/v1` — указывает на SSH reverse tunnel.
> Контейнер запускается с `network_mode: host`, поэтому `localhost:8081`
> внутри контейнера = туннель на хосте.

### Сборка и запуск

```sh
docker compose up -d --build
```

Просмотр логов:

```sh
docker compose logs -f bot
```

Остановка / перезапуск:

```sh
docker compose down      # остановить
docker compose up -d     # перезапустить (без пересборки)
docker compose up -d --build  # пересобрать после изменений в коде
```

### Почему network_mode: host

SSH reverse tunnel приземляется на `127.0.0.1:8081` хоста. В обычном
bridge-режиме Docker `localhost` внутри контейнера изолирован от хоста.
`network_mode: host` объединяет сеть — контейнер видит туннель напрямую.

### Данные

Runtime-данные (`context.json`, `memory.json`, `messages/`, `summaries/`)
хранятся в `./data/` на хосте через bind mount (`./data:/app/data`).
Сохраняются между перезапусками контейнера.

## 4. Порядок запуска

1. Ноут: `bash models/launch3.5-server.sh` (ждать «server is listening»)
2. Ноут: `autossh -M 0 -N -R 8081:localhost:8081 user@SERVER_IP`
3. Сервер: `docker compose up -d --build`

## 5. Диагностика

| Симптом | Причина | Решение |
|---|---|---|
| `Connection refused` на сервере | туннель упал или llama-server не запущен | перезапустить autossh на ноуте |
| `404` / модель не найдена | `--alias` не совпадает с `LLM_MODEL` | проверить `LLM_MODEL=qwen3.5-9b` |
| Ответы с `<think>` | reasoning не выключен | проверить `chat_template_kwargs` в engine.py |
| Timeout | ноут ушёл в сон / медленный | поднять `LLM_REQUEST_TIMEOUT` |
