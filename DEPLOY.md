# Развёртывание на Linux

Нужны Docker Engine и Docker Compose v2 с поддержкой [`env_file.required`](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/) (Compose 2.24 или новее). Команды выполняются из корня проекта. Приложение собирается внутри Docker; устанавливать Python и Node.js на сервер не нужно.

## Первый запуск

```bash
git clone https://github.com/Cheburek254/TravelAIChatbot.git
cd TravelAIChatbot
cp .env.server.example .env
chmod 600 .env
```

Заполните `.env` на сервере:

- `POSTGRES_PASSWORD` — длинный случайный пароль из букв и цифр.
- `OPENROUTER_API_KEY` — ключ OpenRouter. Он остаётся на backend; без ключа работает деморежим.
- `OPENROUTER_MODEL` — идентификатор своей модели; по умолчанию `google/gemini-3.5-flash-lite`. Резервы перечисляются в `OPENROUTER_FALLBACK_MODELS`.
- `YANDEX_RASP_ENABLED` и `YANDEX_RASP_API_KEYS` — включение живых расписаний и ключи. Без них используются явно обозначенные демонстрационные расписания.
- `APP_PUBLIC_PORT` — свободный порт хоста, например `18080`.
- `COMPOSE_PROJECT_NAME` — отдельное постоянное имя проекта, например `travelaichatbot`.

Серверный шаблон привязывает приложение к `127.0.0.1`, чтобы подключить существующий reverse proxy. Для доступа напрямую по IP сервера укажите `APP_BIND_ADDRESS=0.0.0.0`; после запуска адрес будет `http://SERVER_IP:18080`. Доступ к порту также должен быть разрешён в настройках сервера.

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:18080/health
```

Оба сервиса должны иметь статус `healthy`. Внутри контейнера приложение всегда слушает `8080`; внешний порт меняется только через `APP_PUBLIC_PORT`.

## Если на сервере уже есть Nginx

Резервный ИИ-сервис Groq можно включить через `GROQ_API_KEY` в серверном `.env`; адрес API и модели уже указаны в `.env.server.example`. После изменения переменных пересоздайте `app`, чтобы контейнер получил их. Ключи хранятся только в окружении бэкенда; переменные с префиксом `VITE_` для них не используйте.

Приложение рассчитано на корень отдельного домена или поддомена. В существующем `server`-блоке для этого домена настройте:

```nginx
location / {
    proxy_pass http://127.0.0.1:18080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
}
```

Таймаут учитывает время ответа модели и вызовы инструментов. HTTPS настройте в используемом на сервере reverse proxy. Если proxy сам работает в Docker, `127.0.0.1` внутри него указывает на его контейнер: подключите proxy к сети приложения и направьте запросы на сервис `app:8080`.

## Обновление

Сначала создайте резервную копию БД по инструкции ниже. Для развёртывания из Git-клона:

```bash
git switch main
git pull --ff-only origin main
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 90
docker compose ps
curl --fail http://127.0.0.1:18080/health
```

Для существующей установки из архива переносите весь набор отслеживаемых файлов версии в отдельный промежуточный каталог, проверяйте состав архива и делайте копию текущих исходников. Затем заменяйте исходники, сохраняя серверный `.env`, `backups/` и данные PostgreSQL, и пересобирайте приложение. Не включайте локальные `.env`, `.venv`, `node_modules` или `.git` в архив. Если БД уже работает, достаточно `docker compose up --build -d --no-deps --wait --wait-timeout 90 app`.

После изменения ключа или модели в `.env`:

```bash
docker compose up -d --force-recreate app
```

Уже запущенное приложение не получает новые переменные окружения без пересоздания контейнера.

## Данные и диагностика

PostgreSQL доступна только в сети этого Compose-проекта. Каталог и история чатов хранятся в постоянном томе `${COMPOSE_PROJECT_NAME}_postgres_data`. Не меняйте имя проекта при обычном обновлении: другое имя создаст отдельный том и будет выглядеть как пустая база. Копировать локальную базу на сервер для первого запуска не требуется — исходный каталог заполнится автоматически.

```bash
docker compose logs --tail=100 app db
docker compose exec db psql -U travel -d travel
```

Резервная копия из Bash на сервере:

```bash
umask 077
mkdir -p backups
docker compose exec -T db pg_dump -U travel -d travel -Fc > "backups/travel-$(date +%Y%m%d-%H%M%S).dump"
```

После обновления можно повторить backend-проверки внутри приложения без обращений к внешним API:

```bash
docker compose exec -T -e OFFLINE_MODE=1 app python -m unittest discover -s tests -q
```

Проверяйте также новый чат, изменение гостей и номеров, отказ при превышении бюджета и `/health`. Инструкции полного локального набора проверок и установки зависимостей находятся в [README](README.md#проверки-и-бенчмарк).

Обычные `docker compose stop`, `down` и пересборка сохраняют том. `docker compose down -v` удаляет базу — для обновлений эту команду не используйте. Изменение `POSTGRES_PASSWORD` в `.env` не меняет пароль уже созданной базы; для существующего тома смену пароля выполняют отдельно в PostgreSQL.

Текущий запуск использует один процесс приложения. Для демонстрации разным пользователям на общем сервере этого достаточно; несколько копий приложения потребуют дополнительной синхронизации запросов одной сессии.
