# SLUICE — техническая документация (v5)

> SLUICE — медиа-архив: парсит медиа с разделов форума (2ch), скачивает и архивирует
> в объектное хранилище S3 (Timeweb Cloud), каталогизирует и публикует на сайте —
> каталог «досок» → треды → файлы с техпанелью, новинки, топ, поиск, аккаунты и
> премиум-подписка. Тёмный «технический» интерфейс.
>
> Один документ: статус, архитектура, модули, доступ, БД, API, эксплуатация.
> Дизайн-спека: [`DESIGN.md`](DESIGN.md) · Деплой: [`../DEPLOY.md`](../DEPLOY.md) ·
> шаблоны окружения: `.env.example`, `.env.prod.example`, `web/.env.example`.

---

## 0. Быстрый старт

```bash
cp .env.prod.example .env      # заполнить S3_* и ADMIN_TOKEN
docker compose -f docker-compose.prod.yml up -d --build
# сайт: http://localhost:80     админка: http://localhost/admin (токен из .env)
```

Разработка без контейнеров: `postgres`/`redis` в Docker, API —
`uvicorn src.api.main:app --reload`, парсер — `python src/main.py`,
фронт — `cd web && npm run dev`.

## 1. Текущий статус

**Реализовано**

*Парсинг и хранение*
- [x] Парсер 2ch (JSON API): полный и инкрементальный цикл, `parse_mode` доски
      (`all` — все новые треды, `selected` — только включённые вручную), очередь по
      `sort_order`, фильтры размера/разрешения/MIME, поиск по `md5` из API.
- [x] **Идемпотентность повторных проходов**: файл, уже сохранённый в этом треде,
      пропускается (`[have]`), запись без объекта в S3 дозакачивается и обновляется,
      строка-дубль (`duplicate_of_id`) создаётся только для файла из другого
      треда/доски (объект в S3 переиспользуется).
- [x] Коммит БД после каждого треда **и каждые `DB_COMMIT_EVERY_FILES` файлов
      внутри треда** (дефолт 25): частичный прогресс виден сайту сразу, сбой теряет
      максимум пачку; кнопка «Остановить» коммитит уже скачанное.
- [x] S3 (Timeweb Cloud, приватный бакет, path-style): загрузка оригиналов,
      стриминг через API-прокси, reconciliation БД ↔ S3, очистка мусорных объектов.
- [x] Деривативы (Pillow/ffmpeg): `thumb` (~400px WebP), `thumb_blur` (размытый
      превью для премиума), `web` (~1600px WebP), `video` (720p H.264 faststart),
      постер и длительность видео; бэкфилл старых файлов — один запуск проходит всю
      очередь пачками, прогресс «осталось N из M».

*API и сайт*
- [x] FastAPI: публичные роуты (boards / threads / media / feed / top / search),
      статистика просмотров и скачиваний (дедуп по IP), rate limiting на Redis,
      пересчёт popularity.
- [x] Next.js 14: `/` (каталог досок), `/new`, `/top`, `/board/{slug}`, `/search`,
      `/media/{id}`, `/login`, `/profile`, `/admin`; masonry-галерея, infinite
      scroll, lightbox с MD5/SHA-256 и техпанелью, мобильная навигация.
- [x] Дизайн-система SLUICE: токены, JetBrains Mono / Inter, админка в токенах.

*Аккаунты и доступ*
- [x] Аккаунты (`users`/`sessions`): PBKDF2-пароли, httpOnly-сессия `sid` (30 дней),
      `/auth/register|login|logout|me`.
- [x] Оригиналы (`/raw`, `/download`) — только авторизованным.
- [x] **Премиум-доступ**: `boards.is_premium` закрывает все свои треды,
      `threads_state.is_premium` — отдельный тред, `media.is_premium` —
      денормализованный признак для отдачи. Полные версии (`thumb`/`web`/`video`/
      `raw`) — по подписке (403 без неё), публично отдаётся **размытое** превью
      (`thumb_blur`).
- [x] `users.premium_until` + промо-активация премиума на 1 день из профиля
      (платёжного шлюза пока нет).

*Админ-центр (`/admin`)*
- [x] «Мои разделы»: кнопка «Треды» перед «Парсить», переключатели `Парсить` /
      `published|unpublished` / `FREE|PREMIUM`, переименование, удаление (БД + S3),
      статистика, ▲/▼ очередь, прогресс парсера (опрос 1 с).
- [x] Управление тредами: чипы-фильтры (Все / В работе / Парсить / published /
      PREMIUM / Без настроек), поиск, массовые операции, «Сканировать треды»
      (каталог + `?deep=true` — глубокая оценка файлов через `res/{id}.json`).
- [x] «Доски форума»: полный список 2ch из `index.json` со статусами.
- [x] «Оптимизировать медиа»: бэкфилл деривативов с автопродолжением пачками.
- [x] «Очистить S3» (объекты без записей в БД), «Сбросить всё».

*Инфраструктура*
- [x] Docker Compose (postgres, redis, migrate, parser, api, web, nginx) +
      Alembic-миграции на старте; nginx кэширует деривативы на диске
      (`X-Cache-Status`, immutable, `slice` для видео).
- [ ] Прод-деплой на VPS (домен/SSL/выкатка) — **не выполнен**, см. §8.

**Особенности и нюансы (важно для эксплуатации)**
- Счётчики «скачано / в хранилище / видимых / в каталоге» **не учитывают
  дубли-ссылки** (`duplicate_of_id`) — они совпадают с тем, что показывает сайт.
- «Скачано» в статистике доски — это `download_status='downloaded'` (скачано
  локально и **ещё не выгружено** в S3); при работающем S3 смотреть надо «В S3».
- Публичный список тредов показывает только треды, где есть хотя бы один видимый
  файл (пустые карточки-мусор скрыты), поэтому тред появляется на сайте после
  первого коммита своих файлов.
- Премиум-варианты отдаются с `Cache-Control: private, no-store` и в дисковый кэш
  nginx не попадают (иначе файл утёк бы анонимам); публичный `thumb_blur`
  кэшируется надолго.
- Legacy-медиа без `thumb_blur` (до прогона «Оптимизировать медиа») отдаются
  публично как обычное превью + клиентский blur.

**Ограничения и открытые задачи**
- Прод-деплой (домен, SSL, ротация `ADMIN_TOKEN`) — не выполнен.
- Оплата премиума не подключена: активация промо-бесплатная (1 день, продлевается).
- Старые ключи Backblaze, попавшие в git-историю, нужно отозвать и
  вычистить историю (`git filter-repo`, см. `DEPLOY.md`).
- Выкатка «Убрать дубли» из админки — при необходимости повторить чистку
  данных на других инсталляциях (одноразовый SQL в `DEPLOY.md` §Диагностика).

## 2. Архитектура

Один VPS, один Docker Compose-стек: `postgres`, `redis`, `migrate`, `parser`,
`api`, `web`, `nginx`. Наружу открыт только `nginx` (порт `HTTP_PORT`).

| Сервис | Роль | Образ |
|---|---|---|
| `nginx` | точка входа: `/api/*` → api, `/` → web, дисковый кэш деривативов | `nginx:1.27-alpine` |
| `api` | FastAPI (публичные + админ + auth) | `parser-backend:local` |
| `parser` | демон парсинга (включается флагом из админки) | `parser-backend:local` |
| `migrate` | `alembic upgrade head`, затем завершается | `parser-backend:local` |
| `web` | Next.js 14 (SSR + статика) | `parser-web:local` |
| `postgres`, `redis` | БД и состояние/лимиты/прогресс | официальные образы |

Код `api`, `parser` и `migrate` — **общий образ** `parser-backend:local`
(`build:` объявлен только у `api`). Отсюда важный нюанс деплоя: `up -d --build parser`
код не пересобирает — см. `DEPLOY.md` §Диагностика.

**Поток парсинга.** Демон раз в цикл читает флаги из Redis (`parser:enabled`,
`parser:current_board`) → идёт по доскам из БД (`boards.parse_enabled`, `sort_order`)
→ каталог 2ch (`catalog.json`) → для изменившихся тредов `res/{id}.json` → фильтрация
→ скачивание → валидация → загрузка оригинала в S3 → деривативы → запись в БД.
Прогресс пишется в Redis, админка его опрашивает (1 с — прогресс, 2 с — сводка).

**Поток отдачи медиа.** Клиент запрашивает `/api/v1/media/{id}/asset/{kind}` →
nginx (кэш на диске) → api → S3 (поток, без буферизации) → клиент. Оригинал
(`/raw`, `/download`) — только с сессией, премиум-варианты — только с подпиской.

**Ключи в Redis**

| Ключ | Назначение |
|---|---|
| `parser:up` | демон парсера жив (heartbeat, TTL 60 с) |
| `parser:enabled` | парсинг включён (`1`/отсутствует) |
| `parser:alive` | парсер активно работает прямо сейчас |
| `parser:current_board` | slug текущей доски |
| `parser:progress` | JSON прогресса: `phase` (catalog/files), `thread_id`, `files_total`, `files_done`, `updated_at` |
| `backfill:variants` | JSON статуса бэкфилла: `status`, `total`, `done`, `remaining`, `processed`, `errors`, `batch_size` |
| `scan:board:{slug}` | JSON статуса «Сканировать треды» (можно ставить `deep`) |
| `rl:*` | rate limiting по IP (окно 60 с) |

**Кэш nginx** (`proxy_cache_path … keys_zone=media_cache`, `max_size=10g`,
`inactive=30d`): кэшируются только `/api/v1/media/{id}/asset/*`; видео — через
`slice 1m` (Range-запросы). `/view`, `/download`, `/raw` не кэшируются никогда.
`Cache-Control` **не игнорируется** (кроме `Set-Cookie`): ответы `public, immutable`
кэшируются, `private, no-store` — нет.

**Безопасность**
- Пароли — PBKDF2-SHA256 (200k итераций), сессия — случайный токен в httpOnly-cookie
  `sid` (`SameSite=Lax`), в БД хранится только `sha256(токен)`.
- Админ-эндпоинты — `Authorization: Bearer <ADMIN_TOKEN>` (или `X-Admin-Token`).
- Бакет S3 приватный: клиент получает только same-origin URL нашего API.
- Секреты — только в `.env` (не коммитится; `extra="ignore"` в настройках, поэтому
  лишние переменные не ломают старт).

## 3. Модули

### 3.1 Парсер (`src/main.py`, `src/parsers/`)
- Демон всегда запущен; парсинг включается флагом `parser:enabled` (кнопка в админке);
  heartbeat `parser:up` / `parser:alive` / `parser:current_board` (TTL 45–60 с).
- Доски берутся из БД (`boards.parse_enabled`, порядок `sort_order`); `parse_mode`
  доски определяет, включать ли новые треды автоматически.
- Инкрементальный проход: тред пересканируется, если он новый, изменились
  `posts_count`/`files_count` или `last_scanned_at IS NULL`.
- Дедупликация по `md5` из API до скачивания; файл, уже сохранённый **в этом же**
  треде, пропускается; для файла из другого треда создаётся строка-ссылка
  (`duplicate_of_id`, объект S3 переиспользуется).
- Коммит БД после треда + каждые `DB_COMMIT_EVERY_FILES` файлов (дефолт 25);
  `last_scanned_at` обновляется только после полного прохода треда.
- Валидация: MIME (`python-magic`), размер, разрешение, целостность (md5 → SHA-256).
- Reconciliation: сверка БД ↔ S3 и локального кэша (период `RECONCILE_MINUTES`).

### 3.2 Сервисы (`src/services/`)
| Модуль | Назначение |
|---|---|
| `s3_storage` | boto3-клиент S3: `upload_file`, `upload_bytes`, `open_object_stream` (Range), `download_to_file`, `list_keys`, presigned URL (резервный режим) |
| `derivatives` | генерация `thumb` / `thumb_blur` / `web` (WebP) и `video` 720p + постер + длительность (ffmpeg) |
| `media_validator` | классификация типа, проверка размера/разрешения, md5/sha256 |
| `premium` | `premium_active`, `grant_premium`, синхронизация `media.is_premium` при смене флагов доски/треда |
| `auth` | PBKDF2-хеш пароля, токены сессий |
| `thread_discovery` | каталог и треды 2ch, `res/{id}.json` (глубокий скан), `scan:board:{slug}` |
| `storage`, `reconciliation` | локальный кэш и сверка хранилища |

### 3.3 API (`src/api/`)
- Публичные роуты: `boards`, `boards/{slug}/threads`, `boards/{slug}/media`,
  `media/{id}` (+ `view`/`download`/`raw`/`asset/{kind}`), `feed`, `top`, `search`,
  `auth/*`.
- Дубли-ссылки (`duplicate_of_id`) исключены из всех публичных выборок и счётчиков.
- Премиум-гейт: `thumb`/`web`/`video`/`raw` → 403 без подписки; публично доступен
  только размытый `thumb_blur`.
- Админ-роуты (admin-токен): `overview`, `forum`, board CRUD + `reorder` + `delete`,
  `boards/{slug}/threads` (+`PATCH`, `bulk`), `scan` + `scan/status`,
  `backfill-variants` + `status`, `parser/start|stop`, `parser/status`,
  `cleanup-storage`, `reset`, `boards/{slug}/toggle`, `media/{id}/toggle`.
- Rate limiting на Redis; потоковая отдача медиа из S3
  (`S3Storage.open_object_stream`, чанки 256 КБ).

### 3.4 Frontend (`web/`, Next.js 14 App Router)
- Страницы: `/` (каталог досок с фильтрами Все/Без подписки/Премиум), `/new`,
  `/top`, `/board/{slug}` (треды → файлы треда), `/search`, `/media/{id}`,
  `/login`, `/profile`, `/admin`; `web/` standalone-сборка в Docker.
- Показатели: masonry-галерея + infinite scroll, карточки с бейджами
  (`ТОП`, `PREMIUM`, `НЕДОСТУПНО`), lightbox с MD5/SHA-256 и счётчиками,
  бейдж длительности видео, мобильная навигация, `When`-время.
- Премиум в UI: превью размывается (`blur` + бейдж `PREMIUM`), в lightbox вместо
  контента — CTA «Активировать премиум» → `/profile`.
- Авторизация: `AuthMenu` в шапке (email → профиль, «Выйти»), `/login`
  (вход/регистрация), `/profile` (статус премиума, срок, кнопка активации на 1 день).

### 3.5 Админ-центр (`/admin`)
- Вкладки «Мои разделы» и «Доски форума»; парсер: «Запустить/Остановить»,
  прогресс-бар по текущему треду (опрос 1 с), сводка по системе.
- Карточка доски: позиция в очереди (▲/▼), название (переименование), статистика
  (В БД / В S3 / Скачано / Пропущено / В каталоге / Видимых), переключатели
  `Парсить`, `published|unpublished`, `FREE|PREMIUM`, кнопка «Треды».
- Треды доски: чипы-фильтры, поиск по теме/номеру, «в работе» сверху, массовые
  операции (парсить/показать/PREMIUM), «Сканировать треды» (глубокий скан),
  прогресс-бар текущего треда.
- Глобальные операции: «Оптимизировать медиа» (бэкфилл, «осталось N из M»),
  «Очистить S3», «Сбросить всё».
- Легаси-страница `/admin/boards/{slug}` (полный список тредов доски) осталась, но
  из UI больше не линкуется — управление тредами доступно в аккордеоне карточки.

## 4. Доступ: аккаунты и премиум

Раньше закрытый контент открывался «кодом доступа» (cookie `ba_*`/`bt_*`). Сейчас
этот механизм удалён, вместо него — **премиум-подписка**.

| Роль | Что доступно |
|---|---|
| Аноним | каталог/лента/топ/поиск, превью обычных файлов (`thumb`), **размытые** превью премиум-файлов (`thumb_blur`), просмотр оптимизированных `web`/`video` обычных файлов |
| Пользователь (вход) | всё выше + оригиналы (`/raw`, `/download`) обычных файлов |
| Премиум | + полные версии (`thumb`/`web`/`video`) и оригиналы **премиум**-файлов |

Правила премиума:
- `boards.is_premium = true` → закрывает **все** треды доски (в админке у тредов
  переключатель PREMIUM блокируется с пометкой «унаследовано от доски»);
- `threads_state.is_premium = true` → закрывает конкретный тред;
- эффективный признак дублируется в `media.is_premium` (синхронизируется при смене
  флагов и проставляется парсером для новых файлов);
- без подписки `GET /api/v1/media/{id}/asset/{thumb|web|video}` и `/raw` дают
  **403**, а `thumb_blur` отдаётся всегда (публично, кэшируется);
- статус пользователя — `users.premium_until`; активация: `POST
  /api/v1/auth/premium/activate` (промо, `PROMO_PREMIUM_DAYS = 1`, продление
  накопительное). Платёжный шлюз не подключён — это следующий шаг.

## 5. Дизайн (кратко)

Полная спека — [`DESIGN.md`](DESIGN.md). Ключевое:
- тёмный «технический» архив: палитра `ink/text/accent`, без теней и градиентов,
  скругления ≤ 4px; данные — JetBrains Mono, интерфейс — Inter;
- логотип `SLUICE`, навигация: Доски / Новинки / Популярное / Поиск
  (+ мобильная нижняя навигация), аккаунт в шапке;
- бейджи `[ТОП]`, `[PREMIUM]`, `[НЕДОСТУПНО]`, форматы чисел `1.2к` / `1.1М`;
- премиум-превью — размытое изображение с бейджем и CTA на активацию;
- админка — в тех же токенах: моноширинные таблицы, компактные тумблеры, чипы.

## 6. База данных (PostgreSQL, Alembic)

- **boards**: `id, slug, title, description, is_visible, parse_enabled, is_premium,
  parse_mode (all|selected), sort_order, created_at, updated_at`
- **threads_state**: `board_id, thread_id, subject, comment, thread_timestamp,
  posts_count, files_count, files_detected, views_count, last_scanned_at, is_active,
  parse_enabled, is_visible, is_premium` (уникально `board_id + thread_id`)
- **media**: `id, board_id, thread_id, original_name, source_url, source_md5,
  file_hash (sha-256), file_size, mime_type, media_type (image|video), s3_bucket,
  s3_key, local_path, width, height, variants, duration_seconds, is_premium,
  download_status, is_visible, is_active, duplicate_of_id, views_count,
  downloads_count, popularity_score, created_at, updated_at`
- **view_stats / download_stats**: `media_id, ip_hash, viewed_at/downloaded_at`
  (дедуп статистики по IP за 24 ч)
- **users**: `id, email, password_hash, is_active, premium_until, created_at`;
  **sessions**: `user_id, token_hash, expires_at`

Значения:
- `download_status`: `new` → `downloaded` (лежит локально, не выгружен) →
  `uploaded` / `verified` (в S3) либо `missing` (файл потерян).
- `media.variants` (JSON): `thumb`, `thumb_blur`, `web` (для видео — `video`)
  → ключи объектов в S3.
- `duplicate_of_id`: файл-ссылка на уже сохранённый оригинал (тот же `md5` в другом
  треде/доске). Дубли не считаются в статистике и не показываются в галереях.

**Миграции** (Alembic, `alembic upgrade head` выполняется сервисом `migrate`):

```
762df339d1e9  create v3 schema (boards, threads_state, media, view_stats, download_stats)
06bd3e2d4425  add local_path to media
e7f3a1c9b2d4  board management: parse_enabled (+ sort_order позже)
a8b2c4d6e0f2  threads_state: subject / comment / thread_timestamp
c9d0e1f2a3b4  boards.sort_order: очередь парсинга
f1a2b3c4d5e6  хранилище: media.b2_bucket/b2_key → s3_bucket/s3_key
g2h3i4j5k6l7  управление контентом: boards.parse_mode + флаги тредов
h3i4j5k6l7m8  дефолты выключены (новые доски/треды не парсить и не показывать)
i4j5k6l7m8n9  threads_state.views_count (просмотры треда из каталога)
j5k6l7m8n9o0  threads_state.files_detected (файлов по res/{id}.json)
k6l7m8n9o0p1  media.variants (thumb/web) + duration_seconds
l7m8n9o0p1q2  видео-дериватив в ключ 'video' (кэш nginx slice)
m8n9o0p1q2r3  аккаунты: users + sessions
n9o0p1q2r3s4  премиум: boards/threads/media.is_premium, users.premium_until  ← head
```

Полезные запросы:

```sql
-- состояние очереди парсера (что ещё не скачано)
select count(*) filter (where last_scanned_at is null) as not_scanned,
       count(*) filter (where is_active and parse_enabled) as parsing
from threads_state where board_id = $1;

-- сводка по файлам доски (без дублей) — как в админке
select count(*) filter (where duplicate_of_id is null) as files,
       count(*) filter (where duplicate_of_id is null and download_status in ('uploaded','verified')) as in_s3,
       count(*) filter (where duplicate_of_id is not null) as dup_links
from media where board_id = $1;

-- кандидаты на бэкфилл деривативов
select count(*) from media
where s3_key is not null and (variants is null or variants->'thumb_blur' is null);
```

## 7. API (REST)

```text
# публичные (без авторизации):
GET   /api/v1/boards                       доски (вкл. премиум, is_premium)
GET   /api/v1/boards/{slug}/threads        треды доски (метаданные + статистика + превью)
GET   /api/v1/boards/{slug}/media          файлы доски (?thread=&sort=new|popular&type=)
GET   /api/v1/media/{id}                   карточка файла (locked=true — нужна подписка)
GET   /api/v1/media/{id}/view              отметить просмотр (дедуп по IP)
GET   /api/v1/media/{id}/asset/{kind}      kind: thumb | thumb_blur | web | video
GET   /api/v1/feed?type=&page=             новинки (премиум — с размытым превью)
GET   /api/v1/top?type=&period=&limit=     топ: day | week | month
GET   /api/v1/search?q=                    имя файла / md5 / sha-256
GET   /healthz                             healthcheck

# с сессией (cookie sid):
GET   /api/v1/media/{id}/raw[?download=1]  оригинал (премиум-файлы — по подписке)
GET   /api/v1/media/{id}/download          отметить скачивание + URL оригинала
POST  /api/v1/auth/register | /login | /logout
GET   /api/v1/auth/me                      профиль + статус премиума
POST  /api/v1/auth/premium/activate        промо-активация премиума (1 день)

# админ (Authorization: Bearer <ADMIN_TOKEN>):
GET   /api/v1/admin/overview               доски + статистика + статус парсера
GET   /api/v1/admin/parser/status          лёгкий статус: жив, текущая доска, прогресс
POST  /api/v1/admin/parser/start | /stop   включить/остановить парсинг
GET   /api/v1/admin/forum                  доски форума из index.json
GET   /api/v1/admin/boards                 разделы с флагами и статистикой
POST  /api/v1/admin/boards                 добавить раздел по slug
PATCH /api/v1/admin/boards/{slug}          флаги, title, parse_mode, is_premium
DELETE /api/v1/admin/boards/{slug}         удалить раздел (БД + объекты S3)
POST  /api/v1/admin/boards/reorder         порядок очереди парсинга
GET   /api/v1/admin/boards/{slug}/threads  треды раздела (state, q, page)
PATCH /api/v1/admin/boards/{slug}/threads/{id}   флаги треда
POST  /api/v1/admin/boards/{slug}/threads/bulk   массовые флаги
POST  /api/v1/admin/boards/{slug}/scan[?deep=true]   сканировать каталог/файлы
GET   /api/v1/admin/boards/{slug}/scan/status        прогресс сканирования
POST  /api/v1/admin/backfill-variants[?limit=]       бэкфилл деривативов (вся очередь)
GET   /api/v1/admin/backfill-variants/status         прогресс: done/total + remaining
POST  /api/v1/admin/boards/{slug}/toggle             вкл/выкл все треды доски
POST  /api/v1/admin/media/{id}/toggle                скрыть/показать файл
POST  /api/v1/admin/cleanup-storage                  удалить объекты S3 без записей в БД
DELETE /api/v1/admin/reset                           полный сброс (БД + S3)
```

## 8. Эксплуатация и деплой

Подробная инструкция — [`../DEPLOY.md`](../DEPLOY.md). Кратко:

- запуск: `cp .env.prod.example .env` → заполнить `S3_*` и `ADMIN_TOKEN` →
  `docker compose -f docker-compose.prod.yml up -d --build`;
- обновление кода: `git pull && docker compose -f docker-compose.prod.yml up -d --build`
  (помните про общий образ `parser-backend` — §2);
- миграции применяются сервисом `migrate` при старте; текущая голова —
  `n9o0p1q2r3s4`;
- проверка после выкатки: `X-Cache-Status` у `thumb_blur` (`MISS → HIT`), 403 у
  премиум-`web` без подписки, 401 у `/raw` без сессии;
- обязательные переменные парсера: `DB_COMMIT_EVERY_FILES` (дефолт 25),
  `REQUEST_DELAY`, `PARSE_INTERVAL`, `MAX_FILE_SIZE`, `RECONCILE_MINUTES`;
- резервные копии: `pg_dump` + версионирование бакета S3 (см. `DEPLOY.md`);
- диагностика: застрявшие ключи `parser:progress` / `backfill:variants` со статусом
  `running` после аварийного рестарта → `docker compose exec redis redis-cli del …`.

## 9. Планы

1. **Прод-деплой**: домен + SSL (certbot), выкатка compose, мониторинг/uptime,
   ротация `ADMIN_TOKEN`.
2. **Премиум**: подключить оплату (тарифы/сроки), история активаций
   (`premium_orders`), лимиты и приоритеты для подписчиков.
3. **Медиа**: AVIF-превью, HLS/loop-превью видео, CDN перед VPS, прогрев кэша.
4. **Админка**: кнопка «Убрать дубли» (разовый SQL уже отработан), «выбрать всё по
   фильтру» для массовых операций, конфигурируемый порог «простой парсера».
5. **Поиск/UX**: поиск по темам тредов и slug доски, подсветка, пагинация тредов,
   закреплённые треды, доступность/контраст, LCP.
6. **Эксплуатация**: бэкапы БД в S3, логи/ротация, уведомления о лимитах S3,
   сегментация постгреса при росте, второй сервер/очередь (Celery), ИИ-теги.

## 10. Структура репозитория

```
src/                    python-бэкенд
  api/                  FastAPI: роуты (boards/media/feed/top/search/admin/auth),
                        сервисы агрегации (threads_service, stats_service), схемы
  parsers/dvach.py      парсер 2ch (циклы, дедуп, загрузка в S3, деривативы)
  services/             s3_storage, derivatives, premium, auth, thread_discovery,
                        media_validator, storage, reconciliation
  repositories/         доступ к БД (boards/threads/media)
  core/                 config, db, models, redis
migrations/versions/    alembic-миграции (head: n9o0p1q2r3s4)
web/                    Next.js 14: app/ (страницы), components/, lib/
nginx/nginx.conf        конфиг nginx (прокси + дисковый кэш деривативов)
docker-compose.prod.yml, Dockerfile, .env.example, .env.prod.example
DEPLOY.md               деплой, эксплуатация, диагностика
docs/README.md          этот документ
docs/DESIGN.md          дизайн-спека интерфейса
```
