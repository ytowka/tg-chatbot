# Filebrowser: Web UI проводника и редактора

Легковесный веб-проводник + текстовый редактор (~15MB RAM).
Доступ **только через AmneziaWG VPN** (интерфейс `amn0`, IP `172.29.172.1`,
подсеть `172.29.172.0/24`). Снаружи не виден.

Запуск от `root`, корень каталога — `/home/<user>` (замените `<user>` на свой
логин на сервере).

## 1. Установка бинарника

```sh
sudo curl -fsSL https://raw.githubusercontent.com/filebrowser/get/master/get.sh | bash
filebrowser version
```

Бинарник: `/usr/local/bin/filebrowser` (~15MB, статический, без зависимостей).

## 2. Конфигурация

```sh
sudo mkdir -p /etc/filebrowser

sudo filebrowser config init \
  --database /etc/filebrowser/filebrowser.db \
  --address 172.29.172.1 \
  --port 8080 \
  --root /home/<user> \
  --log /var/log/filebrowser.log
```

> ⚠️ `config init` в актуальных версиях **не создаёт** пользователя `admin`
> автоматически. Дефолтный логин `admin/admin` **не работает** — список
> пользователей пуст. Создайте admin-аккаунт явно:

```sh
sudo filebrowser users add admin '<сильный_пароль>' \
  --database /etc/filebrowser/filebrowser.db \
  --perm.admin
```

> Проверено на текущей версии: подкоманда `users add`, пароль — позиционный
> аргумент (флага `--password` нет), админка — `--perm.admin`. В других версиях
> синтаксис может отличаться — см. `filebrowser users add --help`.

Проверить список пользователей и что конфиг записался в БД:

```sh
sudo filebrowser config cat --database /etc/filebrowser/filebrowser.db
```

## 3. systemd-сервис

Создать `/etc/systemd/system/filebrowser.service`:

```ini
[Unit]
Description=Filebrowser Web UI (VPN-only)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/filebrowser --database /etc/filebrowser/filebrowser.db
WorkingDirectory=/etc/filebrowser
Restart=on-failure
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
```

Запуск:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now filebrowser
sudo systemctl status filebrowser
```

## 4. Проверка доступности

**Из клиента внутри VPN** (ваш ноут/телефон с подключённым AmneziaWG):

```sh
curl -I http://172.29.172.1:8080/        # ожидаем 200 OK / 302
```

В браузере: `http://172.29.172.1:8080` → логин `admin` + новый пароль.

**Снаружи (с устройства без VPN)** — должно быть `connection refused` / timeout:

```sh
curl -m 5 http://<SERVER_PUBLIC_IP>:8080/
```

## 5. Опционально: фаервол (второй слой защиты)

На случай компрометации VPN-конфига:

```sh
sudo ufw allow from 172.29.172.0/24 to any port 8080 proto tcp
sudo ufw deny 8080
```

(порядок важен: сначала allow для подсети, потом deny для остальных)

## 6. Обновление

```sh
sudo systemctl stop filebrowser
sudo curl -fsSL https://raw.githubusercontent.com/filebrowser/get/master/get.sh | bash
sudo systemctl start filebrowser
```

БД и конфиг при обновлении сохраняются.

## 7. Управление

```sh
sudo systemctl restart filebrowser       # рестарт
sudo systemctl disable --now filebrowser # остановить и убрать из автозагрузки
sudo journalctl -u filebrowser -f        # логи сервиса
tail -f /var/log/filebrowser.log         # логи приложения
```

### Управление пользователями

Список пользователей и их роли удобнее всего смотреть в **Web UI** без
остановки сервиса: `Settings → User Management`.

Через CLI список пользователей:

```sh
sudo filebrowser users ls --database /etc/filebrowser/filebrowser.db
```

> ⚙️ **БД блокируется запущенным сервисом.** Любые `users`/`config` команды
> через CLI выполняйте **при остановленном filebrowser**, иначе получите
> `Error: timeout` (SQLite `busy_timeout` истекает, пока сервер держит БД):
>
> ```sh
> sudo systemctl stop filebrowser
> sudo filebrowser users ls --database /etc/filebrowser/filebrowser.db
> sudo systemctl start filebrowser
> ```
>
> Если сервис запускался вручную из консоли (без systemd) — остановите его
> `Ctrl+C` в той же консоли или `pkill -f filebrowser`. Проверить, что
> процесс ушёл: `pgrep -fa filebrowser` (пусто = завершён).

Создать ещё одного пользователя, удалить:

```sh
sudo filebrowser users add <name> '<пароль>' --database /etc/filebrowser/filebrowser.db --perm.admin
sudo filebrowser users rm <name>             --database /etc/filebrowser/filebrowser.db
```

Сменить пароль существующему пользователю — точный синтаксис зависит от
версии (позиционный аргумент, как у `add`, либо интерактивный ввод).
Проверьте через `filebrowser users update --help`.

## 8. Диагностика

| Симптом | Причина | Решение |
|---|---|---|
| Не открывается из VPN | упал `amn0` или IP поменялся | `ip -brief a show amn0`, проверить `172.29.172.1` |
| `bind: cannot assign requested address` | `amn0` ещё не поднялся при старте | сервис сам перезапустится (`Restart=on-failure`); поднять вручную `sudo systemctl restart filebrowser` |
| `403` / нет доступа к файлам | права ФС не дают root читать | `ls -la` на целевой каталог; запуск от root обычно решает |
| Не входит `admin/admin` | `config init` не сеет дефолтного admin — список пользователей пуст | создать явно: `users add admin '<пароль>' --perm.admin` (раздел 2) |
| `Error: timeout` на `users ls`/`config cat` | запущенный сервис держит SQLite-БД | остановить сервис, выполнить команду, поднять снова (раздел 7) |
| Снаружи отвечает 200 | бинд на `0.0.0.0` вместо VPN IP | `config cat` → `address` должен быть `172.29.172.1` |
| Пользователи не создаются / игнорируются | `auth.method=noauth` | `config set --auth.method=json`, перезапустить сервис |

## Замечание по безопасности

Запуск от `root` даёт полный доступ к ФС сервера для любого, кто войдёт в
filebrowser. Смените пароль (раздел 2), не включайте в UI «Command Runner»
(Settings → отключить execute), и не расшаривайте admin-аккаунт. При желании
перевести на обычного юзера — достаточно сменить `User=` в systemd-юните и дать
ему права на `/home/<user>`.

Не подставляйте реальные пароли в этот файл — он в git. Используйте плейсхолдер
`<сильный_пароль>` и храните настоящий пароль в менеджере паролей.
