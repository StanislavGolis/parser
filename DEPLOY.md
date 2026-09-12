# Деплой (этап 7) — docker-compose.prod.yml

Единый стек: `postgres` + `redis` + `migrate` + `parser` + `api` + `web` + `nginx`.
Работает одинаково локально (тест «в один клик») и на VPS.

## Локальный запуск

```bash
# из корня репозитория (docker compose v2)
docker compose -f docker-compose.prod.yml up -d --build

# сайт откроется на http://localhost:80 (если 80 занят — укажите другой порт):
HTTP_PORT=8081 docker compose -f docker-compose.prod.yml up -d --build
```

Настройки берутся из `.env` (см. `.env.prod.example`):
- `S3_*` — доступы к приватному бакету S3 (Timeweb Cloud): парсер заливает файлы,
  а API отдаёт их клиенту через прокси (`/api/v1/media/{id}/raw`);
- `BOARDS_TO_PARSE`, `REQUEST_DELAY`, `PARSE_INTERVAL` — поведение парсера;
- `ADMIN_TOKEN`, `API_RATE_LIMIT` — API.

Полезные команды:

```bash
docker compose -f docker-compose.prod.yml ps          # статус
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f parser
docker compose -f docker-compose.prod.yml down         # остановить
docker compose -f docker-compose.prod.yml down -v      # остановить + удалить данные (БД/медиа)
```

## Деплой на VPS (ava.hosting и т.п.)

1. Поставить Docker + Docker Compose plugin (документация провайдера).
2. Забрать код (репозиторий приватный):
   ```bash
   git clone <repo-url> parser && cd parser
   ```
3. Создать `.env` из шаблона и заполнить:
   ```bash
   cp .env.prod.example .env
   nano .env
   ```
4. Запустить:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
5. Настроить домен и SSL (опция):
   - в `nginx/nginx.conf` указать `server_name ваш-домен;`
   - либо поставить Nginx на хост и проксировать, либо использовать
     certbot для контейнера nginx.

Обновление после изменений кода:

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

## Примечания

- Наружу открыт только `nginx` (порт `HTTP_PORT`). PostgreSQL/Redis наружу
  не пробрасываются.
- Данные (тома `pgdata`, `media`) переживают перезапуск; `down -v` удаляет их.
- **Код общий для `api`, `parser` и `migrate`** (образ `parser-backend:local`).
  `build:` объявлен только у сервиса `api`, поэтому `up -d --build parser`
  код НЕ пересобирает (только пересоздаёт контейнер из старого образа).
  Чтобы обновить парсер: `docker compose -f docker-compose.prod.yml up -d --build`
  (весь стек) или `up -d --build api parser`.
- Парсер коммитит БД после каждого треда и каждые `DB_COMMIT_EVERY_FILES`
  файлов внутри треда (дефолт 25, `0` — только по завершении треда): частичный
  прогресс сразу виден на сайте и в статистике, а рестарт теряет максимум пачку
  файлов (незавершённый тред будет докачан в следующий цикл, уже сохранённые
  файлы отсеются по md5 без повторного скачивания).
- Медиа отдаёт наш API (`/api/v1/media/{id}/raw`): файл стримится из приватного S3,
  бакет и его адрес клиенту не раскрываются (nginx: `proxy_buffering off`).
- Nginx кэширует только `/api/v1/media/{id}/asset/*`. Свободные превью и размытые
  премиум-превью (`thumb_blur`) идут с `Cache-Control: public, immutable` и
  кэшируются; премиум-варианты (`thumb`/`web`/`video`) отдаются с
  `Cache-Control: private, no-store` и в кэш НЕ попадают — поэтому в конфиге
  nginx стоит `proxy_ignore_headers Set-Cookie` без игнорирования `Cache-Control`.
  Проверка после деплоя: у `thumb_blur` заголовок `X-Cache-Status` меняется
  `MISS → HIT`, у премиум-`web` всегда `MISS`, у `/view` и `/download` заголовка нет.
- Премиум-доступ: `boards.is_premium` закрывает все треды доски, `threads_state.is_premium` —
  отдельный тред; пользователь активирует подписку в профиле (`/profile`,
  промо на 1 день), статус — `users.premium_until`.
- Если S3 не настроен — парсер складывает файлы в том `media`, а сайт
  показывает заглушки вместо превью (функционал API сохраняется).

## Секреты и переменные окружения

- **Реальные секреты — только в `.env`** (корень репозитория). Файл в `.gitignore` и не коммитится.
- В репозиторий попадают только **шаблоны без секретов**: `.env.example`,
  `.env.prod.example`, `web/.env.example`.
- Локально: `cp .env.example .env`. На VPS: `cp .env.prod.example .env`.
- Секреты не должны попадать в код, логи, конфиги nginx/compose и в git-историю.
- Если секрет уже попал в коммит — **сначала отзовите/смените его**, затем чистите историю.

Очистка истории от случайно закоммиченного `.env` (git-filter-repo):

```bash
pip install git-filter-repo
git filter-repo --invert-paths --path .env
git push --force --all
git push --force --tags
```

После перезаписи истории в других клонах: `git fetch --all && git reset --hard origin/main`.
