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
   cat >/etc/nginx/sites-available/dredge <<'EOF'
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
   ln -s /etc/nginx/sites-available/dredge /etc/nginx/sites-enabled/dredge
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

## Переезд на VPS: пошагово (ava.hosting)

Порядок для чистого сервера Ubuntu 22.04/24.04. Медиа уже лежат в S3 (тот же
бакет), поэтому переносим только код, `.env` и базу.

### 1. Сервер: Docker + firewall

```bash
apt update && apt upgrade -y
apt install -y ca-certificates curl git ufw
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt update && apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
```

### 2. Доступ по SSH-ключу

Локальный публичный ключ (`~/.ssh/id_ed25519.pub`) добавить в панели ava.hosting
или прямо на сервере:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'ssh-ed25519 AAAA... ваш-ключ' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Потом вход по паролю можно отключить (`PasswordAuthentication no`).

### 3. Код (репозиторий приватный)

```bash
ssh-keygen -t ed25519 -C "vps-dredge" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub     # добавить в GitHub → Settings → Deploy keys (read-only)
git clone git@github.com:StanislavGolis/parser.git /opt/dredge && cd /opt/dredge
```

Либо HTTPS-клонирование с Personal Access Token вместо пароля.

### 4. `.env`

```bash
cp .env.prod.example .env
openssl rand -hex 32   # → ADMIN_TOKEN
openssl rand -hex 24   # → POSTGRES_PASSWORD
nano .env
```

Обязательно проверить: `S3_*` (те же, что локально), `ADMIN_TOKEN` и
`POSTGRES_PASSWORD` — новые, `HTTP_PORT=8080` (если SSL терминирует nginx хоста,
шаг 6), `SESSION_COOKIE_SECURE=1`, `SQL_ECHO=0`,
`API_CORS_ORIGINS=https://<домен>`, `BOARDS_TO_PARSE`, `PARSE_INTERVAL=60`.

### 5. Перенос базы с локальной машины

Медиа (S3) переносить не нужно — копируем только дамп базы (~0.5 КБ на файл).

```bash
# ЛОКАЛЬНО: дамп в custom-формате (сжатый) прямо внутри контейнера
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U parser -d parser -Fc -f /tmp/dredge.pgc
docker compose -f docker-compose.prod.yml cp postgres:/tmp/dredge.pgc ./dredge-$(date +%F).pgc
docker compose -f docker-compose.prod.yml exec -T postgres rm -f /tmp/dredge.pgc
scp dredge-$(date +%F).pgc root@<VPS>:/root/
```

```bash
# НА VPS: только БД → восстановление → весь стек
cd /opt/dredge
docker compose -f docker-compose.prod.yml up -d postgres
docker compose -f docker-compose.prod.yml cp /root/dredge-$(date +%F).pgc postgres:/tmp/dredge.pgc
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_restore -U parser -d parser --clean --if-exists /tmp/dredge.pgc
docker compose -f docker-compose.prod.yml exec -T postgres rm -f /tmp/dredge.pgc
docker compose -f docker-compose.prod.yml up -d --build
```

Проверка: `select version_num from alembic_version;` (должна совпасть с локальной —
`s4t5u6v7w8x9`), `select count(*) from media;`, `select count(*) from users;`.
Схема уже накатана сервисом `migrate`, поэтому `--clean --if-exists` в
`pg_restore` безопасен (объекты удаляются и создаются заново). Том `media` на VPS
останется пустым — это локальный кэш, он заполняется сам при доставке файлов из S3.

### 6. Домен и SSL (хост-nginx, вариант A)

Сначала DNS: A-запись `<домен>` → IP VPS.

```bash
apt install -y nginx certbot python3-certbot-nginx
cat >/etc/nginx/sites-available/dredge <<'EOF'
server {
    listen 80;
    server_name <домен>;
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 0;
        proxy_read_timeout 300s;
    }
}
EOF
ln -s /etc/nginx/sites-available/dredge /etc/nginx/sites-enabled/dredge
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
certbot --nginx -d <домен> --agree-tos -m <email> --redirect
```

`X-Forwarded-Proto` нужен для корректных ссылок, `X-Forwarded-For` — чтобы
rate-limit и статистика видели IP посетителя (API берёт его из этого заголовка).

### 7. Бэкапы по cron

```bash
mkdir -p /opt/dredge/backups
cat >/etc/cron.daily/dredge-backup <<'EOF'
#!/bin/sh
cd /opt/dredge || exit 1
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U parser -d parser -Fc -f /tmp/dredge.pgc
docker compose -f docker-compose.prod.yml cp postgres:/tmp/dredge.pgc "backups/db-$(date +%F).pgc"
docker compose -f docker-compose.prod.yml exec -T postgres rm -f /tmp/dredge.pgc
find backups -name 'db-*.pgc' -mtime +14 -delete
EOF
chmod +x /etc/cron.daily/dredge-backup
```

Восстановление из бэкапа: `pg_restore -U parser -d parser --clean --if-exists`
(как в шаге 5). Медиа в бэкап не входят — они в S3 (включите версионирование бакета).

### 8. Безопасность сразу после переезда

- `ADMIN_TOKEN` и `POSTGRES_PASSWORD` — только новые (шаг 4).
- **Отозвать старые ключи Backblaze** (`B2_KEY_ID`/`B2_APPLICATION_KEY` попали в
  git-историю в старом `.env`) и вычистить историю (`git filter-repo`, §Секреты).
  Ключи Timeweb S3 в историю не попадали — их менять не обязательно.
- Наружу только 22/80/443: PostgreSQL и Redis в compose портов не публикуют.

### 9. Что уже сделано на нашем VPS

| Параметр | Значение |
|---|---|
| Сервер | `37.221.66.168`, Ubuntu 24.04.5 LTS, 4 vCPU / 8 ГБ RAM / 87 ГБ SSD |
| Каталог | `/opt/dredge` (первичный клон из `git bundle`; `origin` → `git@github-dredge:StanislavGolis/parser.git`) |
| Доступ | ключ владельца + deploy-key сервера `/root/.ssh/dredge_deploy` (alias `github-dredge` в `~/.ssh/config`) |
| Стек | `docker compose -f docker-compose.prod.yml`, nginx слушает `:80` (этап 1 — IP без домена) |
| `.env` | `HTTP_PORT=80`, `SESSION_COOKIE_SECURE=0`, `SQL_ECHO=0`, новые `ADMIN_TOKEN`/`POSTGRES_PASSWORD` |
| База | восстановлена из дампа: head `s4t5u6v7w8x9`, media 3557 (все в S3), users 1, boards 2, threads 223 |
| Бэкапы | `/etc/cron.daily/dredge-backup` → `/opt/dredge/backups/db-<дата>.pgc`, хранение 14 дней (пробный прогон сделан) |
| Парсер | **на паузе** (ключ `parser:enabled` не выставлен) — включается кнопкой «Запустить» в админке |
| Проверено | `/healthz` 200, главная 200, `/admin` 200, `thumb_blur` 200 + `X-Cache: MISS→HIT`, `/raw` 401 анониму, `/marks` 401, запись в S3 (`put/delete`) ok |
| Локальный стек | парсер остановлен, чтобы два процесса не работали с одним бакетом S3 |

**Этап 2 (когда будет домен):** A-запись → `37.221.66.168`; `apt install nginx certbot
python3-certbot-nginx`; конфиг из шага 6 (`server_name <домен>`, `proxy_pass 127.0.0.1:8080`);
в `.env` → `HTTP_PORT=8080`, `SESSION_COOKIE_SECURE=1`, `API_CORS_ORIGINS=https://<домен>`;
`docker compose -f docker-compose.prod.yml up -d`; `certbot --nginx -d <домен> --redirect`.

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
- [ ] `/raw` без сессии → 401, зарегистрированному без подписки → 403,
      премиум-подписчику → 200/206 (скачивание и оригиналы — только премиум);
- [ ] метка: анониму 401, после входа 200 и файл появляется на `/marks`
      (`/favorites` редиректит на `/marks`);
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

**Тред «не докачивается», число скачанных файлов стоит на месте.** В логе парсера
ищите `duplicate key value violates unique constraint "media_file_hash_key"` —
контент файла (SHA-256) уже есть в БД под другим `source_md5` (CDN пережимает
картинки). Раньше такая ошибка «травила» транзакцию треда: следующие файлы падали
с «transaction has been rolled back», а цикл перезапускался на том же месте — тред
никогда не доходил до конца. Сейчас конфликт `file_hash` превращается в
дубль-ссылку (`[dup] Дубль по sha256`), а запись файла идёт в SAFEPOINT, поэтому
один файл не может уронить тред.

```sql
-- состояние треда: last_scan_attempt_at обновляется, last_scanned_at — нет
select thread_id, pending_scan, pending_reason, files_detected, last_scanned_at,
       last_scan_attempt_at
from threads_state where thread_id = <ID>;

select download_status, count(*), count(s3_key) from media
where board_id = <BOARD_ID> and thread_id = <ID> group by 1;
```

Принудительно вернуть тред в очередь: кнопка «В очередь» в админке или

```bash
curl -X PATCH -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"requeue": true}' \
  "$BASE/api/v1/admin/boards/<slug>/threads/<ID>"
```

**«Ошибка 500» при сканировании раздела.** Так проявляется удалённая доска:
`index.json` 2ch продолжает её перечислять, а сам раздел отдаёт `500 Not found`
(например хентай-разделы `/h`, `/ho`, `/hc` — их на форуме больше нет, работают
`/sex`, `/fag`, `/gg`, `/fur`). Проверить руками:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://2ch.hk/h/catalog.json   # 500 -> раздела нет
curl -s -o /dev/null -w '%{http_code}\n' https://2ch.hk/sex/catalog.json # 200 -> живой
```

В админке у такого раздела появляется бейдж «каталог недоступен» (причина — в
подсказке), при попытке добавить удалённый слаг создание отклоняется с 400, а
«Сканировать треды» показывает человеческий текст вместо кода 500. Такой раздел
надо удалить (корзина на карточке) или заменить на живой.

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
| `ADMIN_TOKEN` | — | токен админ-эндпоинтов (`Authorization: Bearer …`); **сменить на случайный** (`openssl rand -hex 32`) |
| `SQL_ECHO` | `0` | логировать SQL-запросы (в проде держать `0`: с `1` логи растут гигабайтами) |
| `SESSION_COOKIE_SECURE` | `0` | cookie сессии только по HTTPS: на VPS с SSL → `1`, локально без сертификата → `0` |
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
| `DEAD_THREAD_AFTER_MISSES` | `3` | столько проходов каталога подряд тред может отсутствовать → `is_active=false` |
| `STALE_SCAN_HOURS` | `24` | тред не сканировался дольше → «просрочен» (попадает в плановый догон) |
| `PARSE_CYCLE_BUDGET_MINUTES` | `30` | бюджет фазы B цикла парсинга, мин (`0` — без лимита) |
| `MAX_PARALLEL_DOWNLOADS` | `2` | сколько файлов качать одновременно внутри треда (`1` — последовательно) |
| `PREFETCH_MAX_BYTES` | `67108864` | ограничение памяти под предзагрузку пачки файлов (64 МБ) |
| `MAX_PARALLEL_UPLOADS` | `1` | параллельные выгрузки в S3 внутри треда; `>1` проверять замером — Timeweb-эндпоинт троттлит одновременные загрузки (10.9 → 3.0 МБ/с) |
| `NEXT_PUBLIC_API_BASE` (web) | пусто | URL API для браузера; пусто = same-origin (в compose не задаётся) |
| `API_BASE_SERVER` (web) | `http://api:8000` | URL API для SSR внутри docker-сети (задан в compose) |
