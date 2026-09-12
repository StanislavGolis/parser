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

Настройки берутся из `.env` (см. `.env.prod.example`) — полный список переменных
с пояснениями в разделе «Переменные окружения» в конце документа. Минимально нужно
заполнить: `S3_*` (доступы к приватному бакету Timeweb Cloud — парсер заливает файлы,
API отдаёт их через прокси `/api/v1/media/{id}/raw`) и `ADMIN_TOKEN` (токен админки).

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
5. Настроить домен и SSL. Два рабочих варианта:

   **A. Nginx на хосте (проще всего, контейнер отдаёт HTTP).**
   ```bash
   apt install -y nginx certbot python3-certbot-nginx
   # HTTP_PORT=8080 в .env, чтобы контейнер не занимал 80/443
   docker compose -f docker-compose.prod.yml up -d
   cat >/etc/nginx/sites-available/sluice <<'EOF'
   server {
       listen 80;
       server_name example.com;
       location /.well-known/acme-challenge/ { root /var/www/html; }
       location / { proxy_pass http://127.0.0.1:8080; proxy_set_header Host $host;
                    proxy_set_header X-Real-IP $remote_addr;
                    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                    client_max_body_size 0; }
   }
   EOF
   ln -s /etc/nginx/sites-available/sluice /etc/nginx/sites-enabled/sluice
   nginx -t && systemctl reload nginx
   certbot --nginx -d example.com        # сам впишет 443 и редирект с 80
   ```
   Плюс: конфиг compose и nginx-контейнера не меняется.

   **B. SSL внутри контейнера nginx (webroot).** Нужно добавить в
   `docker-compose.prod.yml` том для challenge и смонтировать сертификаты:
   ```yaml
   nginx:
     volumes:
       - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
       - nginx_cache:/var/cache/nginx/media
       - ./certbot/www:/var/www/certbot:ro
       - ./certbot/conf:/etc/letsencrypt:ro
   ```
   и в `nginx/nginx.conf` — `location /.well-known/acme-challenge/ { root /var/www/certbot; }`
   плюс `server { listen 443 ssl; ssl_certificate /etc/letsencrypt/live/<домен>/fullchain.pem; … }`.
   Выпуск/продление:
   ```bash
   docker run --rm -v "$PWD/certbot/www:/var/www/certbot" \
     -v "$PWD/certbot/conf:/etc/letsencrypt" certbot/certbot \
     certonly --webroot -w /var/www/certbot -d example.com --agree-tos -m admin@example.com
   docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
   ```
   Автопродление — cron/systemd-timer с той же командой `certonly --webroot`.

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

## Проверка после деплоя

```bash
BASE=https://example.com
TOKEN=<ADMIN_TOKEN>

curl -s $BASE/healthz
curl -s "$BASE/api/v1/boards" | head -c 400            # каталог досок (+ is_premium)
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/admin/parser/status"
# премиум-гейт и кэш (подставить id премиум-файла):
curl -s -o /dev/null -w '%{http_code}\n' "$BASE/api/v1/media/<id>/asset/web"   # 403 без подписки
curl -s -D - -o /dev/null "$BASE/api/v1/media/<id>/asset/thumb_blur" \
  | grep -Ei 'x-cache-status|cache-control'                                     # MISS → HIT
curl -s -o /dev/null -w '%{http_code}\n' "$BASE/api/v1/media/<id>/raw"          # 401 без сессии
```

Чек-лист:
- [ ] `/healthz` отвечает, `docker compose ps` — все сервисы `healthy`;
- [ ] каталог досок и админский `/overview` отдают данные (миграции применены);
- [ ] `thumb_blur` кэшируется (`MISS → HIT`), премиум-`web` — всегда `MISS` (или 403),
      у `/view` и `/download` заголовка `X-Cache-Status` нет;
- [ ] `/raw` без сессии → 401, после входа — 200;
- [ ] регистрация → «Активировать премиум» в `/profile` → премиум-файл открывается;
- [ ] парсер запускается из админки, в треде появляются записи (и на сайте).

## Диагностика

**`up -d --build parser` не обновляет код парсера.** `api`, `parser` и `migrate`
используют общий образ `parser-backend:local`, а `build:` объявлен только у `api`.
Собирать так:

```bash
docker compose -f docker-compose.prod.yml up -d --build              # весь стек
docker compose -f docker-compose.prod.yml up -d --build api parser   # api пересоберёт образ
# проверка, что код внутри свежий:
docker compose -f docker-compose.prod.yml exec parser python -c \
  "import src.core.config as c; print(c.settings.DB_COMMIT_EVERY_FILES)"
```

**Застрял статус `running` в Redis** (парсер/бэкфилл прерваны рестартом):

```bash
docker compose -f docker-compose.prod.yml exec redis redis-cli get parser:progress
docker compose -f docker-compose.prod.yml exec redis redis-cli del parser:progress
docker compose -f docker-compose.prod.yml exec redis redis-cli del backfill:variants
```

`backfill:variants` со статусом `running` блокирует кнопку «Оптимизировать медиа»
до истечения TTL (2 ч); удаление ключа разблокирует её, прогон безопасно
перезапустить — очередь считается по БД (файлы без `thumb_blur`).

**Строки-дубли одного файла** (старые базы, `duplicate_of_id` указывает на тот же
тред) удаляются разово; файлы в S3 и оригинальные записи не затрагиваются:

```sql
begin;
create temp table dup_ids on commit drop as
  select m.id from media m join media o on o.id = m.duplicate_of_id
  where m.board_id = o.board_id and m.thread_id = o.thread_id;
delete from view_stats     where media_id in (select id from dup_ids);
delete from download_stats where media_id in (select id from dup_ids);
delete from media          where id in (select id from dup_ids);
commit;
```

```bash
docker compose -f docker-compose.prod.yml exec -T postgres psql -U parser -d parser -c "analyze media;"
```

Статистика в админке дубли не считает, поэтому числа корректны и без чистки.

**Место на диске**: кэш nginx до 10 ГБ (том `nginx_cache`) + медиа-том (`media`);
`docker system df`, при росте — увеличить диск VPS или уменьшить `max_size`
в `nginx/nginx.conf`.

**Парсер «молчит»**: проверить ключи `parser:up` / `parser:alive` / `parser:enabled`
и логи (`docker compose … logs -f parser`); в админке при простое > 60 с полоса
становится красной и пишет «возможно завис».

## Бэкапы

```bash
# дамп БД
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U parser -d parser | gzip > backup-$(date +%F).sql.gz
# восстановление
gunzip -c backup-2026-09-12.sql.gz | docker compose -f docker-compose.prod.yml \
  exec -T postgres psql -U parser -d parser
```

- Медиа живут в S3: включите версионирование бакета и правило жизненного цикла
  (в т.ч. удаление незавершённых multipart-загрузок).
- Тома `pgdata`/`media` переживают перезапуск, но `down -v` их удаляет.

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

## Переменные окружения

Читаются из `.env` (pydantic-settings; лишние ключи игнорируются, поэтому старые
переменные не ломают запуск).

| Переменная | Дефолт | Назначение |
|---|---|---|
| `HTTP_PORT` | `80` | внешний порт nginx (локально удобно `8081`) |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `parser` / `parser` / — | креды БД стека; пароль обязательно сменить |
| `ADMIN_TOKEN` | — | токен админ-эндпоинтов (`Authorization: Bearer …`); **сменить на случайный** |
| `API_RATE_LIMIT` | `60` | лимит публичных запросов в минуту на IP (0 — выключить) |
| `API_CORS_ORIGINS` | `http://localhost` | CORS (фронт ходит через тот же origin, поэтому не критично) |
| `POPULARITY_RECALC_MINUTES` | `5` | период пересчёта `popularity_score` |
| `S3_URL` | `https://s3.twcstorage.ru` | endpoint S3 |
| `S3_REGION` | `ru-1` | регион бакета |
| `S3_BUCKET` | — | имя бакета (в Timeweb это UUID) |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | — | ключи доступа (секреты, только в `.env`) |
| `S3_ADDRESSING_STYLE` | `path` | path-style: обязателен, т.к. имя бакета — UUID |
| `S3_SIGNED_URL_TTL` | `3600` | срок жизни presigned-URL (резервный режим отдачи) |
| `MEDIA_DELIVERY` | `proxy` | `proxy` — отдача через API (бакет не раскрывается); `presigned` — прямые ссылки |
| `BOARDS_TO_PARSE` | `["b"]` | bootstrap: какие доски создать в БД при первом запуске (дальше — флаги в БД) |
| `PARSE_INTERVAL` | `30` (`60` в prod-шаблоне) | пауза между циклами парсинга, сек |
| `REQUEST_DELAY` | `0.5` | задержка между запросами к форуму (защита от бана), сек |
| `DB_COMMIT_EVERY_FILES` | `25` | коммит БД каждые N файлов внутри треда (`0` — только после треда) |
| `MAX_FILES_PER_POST` | `5` | ограничение числа файлов на пост |
| `MAX_FILE_SIZE` | `104857600` | максимальный размер файла, байт (100 МБ) |
| `RECONCILE_MINUTES` | `60` | период сверки БД ↔ S3, мин (`0` — только при старте) |
| `NEXT_PUBLIC_API_BASE` (web) | пусто | URL API для браузера; пусто = same-origin (в compose не задаётся) |
| `API_BASE_SERVER` (web) | `http://api:8000` | URL API для SSR внутри docker-сети (задан в compose) |
