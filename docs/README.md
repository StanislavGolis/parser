# DREDGE — техническая документация (v6)

> DREDGE — архив // отбор // доступ: медиа-архив, который парсит медиа с разделов
> форума (2ch), скачивает и архивирует в объектное хранилище S3 (Timeweb Cloud),
> каталогизирует и публикует на сайте — каталог «досок» → треды → файлы с
> техпанелью, новинки, топ, поиск, аккаунты, **метки** («отличный контент»,
> наш аналог лайка) и премиум-подписка. Тёмный «технический» интерфейс.
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
      треда/доски (объект в S3 переиспользуется). Конфликт **SHA-256** (CDN
      пережимает картинки — один контент под разными `md5`) тоже становится
      строкой-дублем: без этого INSERT падал на `UNIQUE(media.file_hash)` и тред не
      мог пройти полный прогон. Запись файла идёт в SAVEPOINT, ошибка одного файла
      не роняет тред, а в конце треда печатается сводка `[done]`
      (saved/have/dup/invalid/filtered/err).
- [x] **Двухфазный цикл и очередь докачки**: фаза A — каталоги всех парсируемых
      досок (1 запрос на доску), фаза B — загрузка по очереди из БД
      (`pending_scan`): свежие изменения вперёд, затем LRU; очередь переживает
      перезапуск, `PARSE_CYCLE_BUDGET_MINUTES` ограничивает цикл, доски чередуются
      (round-robin) — одна доска с длинной очередью не держит остальные.
- [x] **Гигиена обхода**: `misses`/`missing_since` — тред гасится только после
      `DEAD_THREAD_AFTER_MISSES` промахов каталога (обрезанный каталог 2ch больше не
      «убивает» живые треды); `STALE_SCAN_HOURS` — плановый догон; метрика
      «Недокачано» (`files_detected` без файлов, отброшенных правилами размера).
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
- [x] Дизайн-система DREDGE (бывш. SLUICE): токены, JetBrains Mono / Inter,
      админка в токенах.

*Аккаунты и доступ*
- [x] Аккаунты (`users`/`sessions`): PBKDF2-пароли, httpOnly-сессия `sid` (30 дней),
      `/auth/register|login|logout|me` (+ счётчик меток в профиле).
- [x] Матрица ролей: **аноним** — только просмотр (лента/топ/поиск, включая
      размытые превью премиума); **зарегистрированный** — метки,
      размытые превью премиума; **премиум** — премиум-разделы, скачивание,
      оригиналы. Скачивание и оригиналы (`/raw`, `/download`) — только премиум
      (аноним → 401, без подписки → 403).
- [x] **Метка** («отличный контент») — единая пользовательская отметка (аналог
      лайка): переключатель на карточке и в lightbox (плюс пробел при просмотре),
      счётчик `media.marks_count`, вес в индексе популярности, сортировка
      `sort=marks` и личный список «мои метки» — страница `/marks`
      (`GET /api/v1/marks`; старый `/favorites` редиректит). Требует аккаунт.
      Отдельного «избранного» больше нет: оно объединено с метками
      (миграция `p1q2r3s4t5u6`).
- [x] **Премиум-доступ**: `boards.is_premium` закрывает все свои треды,
      `threads_state.is_premium` — отдельный тред, `media.is_premium` —
      денормализованный признак для отдачи. Полные версии (`thumb`/`web`/`video`)
      и оригиналы — по подписке (403 без неё), публично отдаётся **размытое**
      превью (`thumb_blur`); при активной подписке блюр снимается, бейдж
      переключается с замка на звезду.
- [x] `users.premium_until` + промо-активация премиума на 1 день из профиля
      (платёжного шлюза пока нет).

*Админ-центр (`/admin`)*
- [x] «Мои разделы»: кнопка «Треды» перед «Парсить», переключатели `Парсить` /
      `published|unpublished` / `FREE|PREMIUM`, переименование, удаление (БД + S3),
      статистика, ▲/▼ очередь, прогресс парсера (опрос 1 с).
- [x] Управление тредами: чипы-фильтры (Все / В работе / Парсить / published /
      PREMIUM / **В очереди** / **Недокачано** / **Просроченные** / **Мёртвые** /
      Без настроек), поиск, массовые операции (вкл/выкл парсинга, показа, PREMIUM,
      **«Вернуть в обход»**, **«В очередь»**), «Сканировать треды»
      (каталог + `?deep=true` — глубокая оценка файлов через `res/{id}.json`).
      В строке треда: причина очереди, дата последней попытки, у мёртвого — дата
      исчезновения и число промахов, у просроченного — «попытка: …».
- [x] «Доски форума»: полный список 2ch из `index.json` со статусами; добавление
      слага проверяется по каталогу (удалённый раздел не добавить), у недоступного
      каталога карточка показывает бейдж **«каталог недоступен»** с причиной
      (Redis `board:catalog_error:{slug}`), «Сканировать треды» отдаёт человеческий
      текст ошибки вместо сырого 500.
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
| `board:catalog_error:{slug}` | JSON `{text, at}` — каталог раздела не читается (2ch отдал 500/404: доска удалена); TTL 6 ч, снимается успешным чтением |
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
- Двухфазный цикл (чтобы ни одна доска не «залипала»):
  **фаза A** — дёшево обновляются каталоги всех парсируемых досок (1 запрос на
  доску) и помечаются треды `pending_scan` с причиной; **фаза B** — докачка по
  очереди из БД. Порядок очереди: «новый»/«изменения»/«файлы» (свежие файлы на
  форуме) → «просрочен»/«не скачивался», внутри групп — по «давности»
  сканирования (`last_scanned_at`, LRU). Очередь хранится в БД, поэтому
  перезапуск парсера её не теряет (курсор не нужен); тред, у которого
  `res/{id}.json` не прочитался, остаётся в очереди.
- Бюджет цикла и чередование досок: `PARSE_CYCLE_BUDGET_MINUTES` (дефолт 30) —
  после бюджета фаза B прерывается, остаток очереди продолжается в следующем
  цикле; внутри фазы B доски чередуются (round-robin), поэтому одна доска с
  длинной очередью не держит остальные.
- Гигиена обхода (чтобы не было «забытых» тредов): тред, выпавший из каталога
  доски, получает `misses`/`missing_since` и гасится (`is_active=false`) только
  после `DEAD_THREAD_AFTER_MISSES` проходов подряд — обрезанный каталог 2ch
  больше не прячет живые треды; треды, которые давно не сканировались
  (`STALE_SCAN_HOURS`, дефолт 24 ч), попадают в очередь планового догона, а в
  админке видны чипами «В очереди»/«Просроченные»/«Мёртвые»/«Недокачано».
- `files_detected` («файлов на форуме») — это файлы, которые **мы должны были
  сохранить**: обновляется при каждом скане треда (без лишних запросов) и не
  включает мелочь, отброшенную правилами размера/разрешения (у 2ch у удалённых
  вложений остаются «заглушки» в 5–47 байт). Поэтому «Недокачано» — это реальные
  пропуски (битые файлы, ошибки сети/S3), а не шум: такие треды можно поставить
  в очередь кнопкой «В очередь».
- Дедупликация по `md5` из API до скачивания; файл, уже сохранённый **в этом же**
  треде, пропускается; для файла из другого треда создаётся строка-ссылка
  (`duplicate_of_id`, объект S3 переиспользуется). Если `md5` на форуме не совпал,
  но **SHA-256 контента** уже есть в БД (CDN пережимает картинки) — строка-ссылка
  создаётся по SHA-256: без этого вставка падала на `UNIQUE(media.file_hash)` и
  тред не мог пройти полный прогон.
- Запись файла идёт в SAVEPOINT, а ошибка одного файла не роняет тред и цикл:
  файл пропускается с `[err]`, тред остаётся в очереди и докачивается позже.
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
  `marks` («мои метки»), `auth/*`.
- Дубли-ссылки (`duplicate_of_id`) исключены из всех публичных выборок и счётчиков.
- Премиум-гейт: `thumb`/`web`/`video`/`raw`/`download` → 403 без подписки (401 анониму);
  публично доступен только размытый `thumb_blur`.
- Метка: `POST /media/{id}/mark` (переключатель, требует аккаунт); в списках
  отдаются `marks_count`, `marked` (по одному запросу на страницу).
- Админ-роуты (admin-токен): `overview`, `forum`, board CRUD + `reorder` + `delete`,
  `boards/{slug}/threads` (+`PATCH`, `bulk`), `scan` + `scan/status`,
  `backfill-variants` + `status`, `parser/start|stop`, `parser/status`,
  `cleanup-storage`, `reset`, `boards/{slug}/toggle`, `media/{id}/toggle`.
- Rate limiting на Redis; потоковая отдача медиа из S3
  (`S3Storage.open_object_stream`, чанки 256 КБ).

### 3.4 Frontend (`web/`, Next.js 14 App Router)
- Страницы: `/` (каталог досок с фильтрами Все/Без подписки/Премиум), `/new`,
  `/top`, `/board/{slug}` (треды → файлы треда), `/search`, `/media/{id}`,
  `/marks` («мои метки»; `/favorites` редиректит сюда), `/login`, `/profile`,
  `/admin`; `web/` standalone-сборка.
- Показатели: masonry-галерея + infinite scroll, карточки с бейджами
  (`ТОП`, `PREMIUM` 🔒/★, `НЕДОСТУПНО`), кнопка «метка» (🏷) поверх превью и в
  lightbox, маркер видео (значок ▶ + длительность) на карточках, превью тредов и
  в карусели просмотра, мобильная навигация (5 пунктов), `When`-время.
- Lightbox: перелистывание `←`/`→` **и колесом мыши** (порог + кулдаун, чтобы не
  проматывать пачками; Ctrl+колесо — зум браузера, над лентой миниатюр колесо не
  листает), **пробел — метка** «отличный контент» с плашкой-подтверждением,
  `Esc` — закрыть, клик по фону — закрыть.
- Премиум в UI: превью размывается (`blur` + 🔒), в lightbox вместо контента — CTA
  «Активировать премиум» → `/profile`; при активной подписке превью открыто, бейдж ★.
- Авторизация: `AuthMenu` в шапке (email → профиль, «Выйти»), `/login`
  (вход/регистрация), `/profile` (статус премиума, срок, активация на 1 день,
  счётчик меток со ссылкой на `/marks`).
- Брендинг: `DREDGE` — «архив // отбор // доступ» (логотип в шапке, title/шаблон
  в `layout.tsx`, подвал), классы дизайн-системы `dredge-title` / `input-dredge`.

### 3.5 Админ-центр (`/admin`)
- Вкладки «Мои разделы» и «Доски форума»; парсер: «Запустить/Остановить»,
  прогресс-бар по текущему треду (опрос 1 с), сводка по системе.
- Карточка доски: позиция в очереди (▲/▼), название (переименование), статистика
  (В БД / В S3 / Скачано / Пропущено / В каталоге / Видимых), переключатели
  `Парсить`, `published|unpublished`, `FREE|PREMIUM`, кнопка «Треды».
- Треды доски: чипы-фильтры, поиск по теме/номеру, «в работе» сверху, массовые
  операции (парсить/показать/PREMIUM/«вернуть в обход»), «Сканировать треды»
  (глубокий скан), прогресс-бар текущего треда.
- Гигиена обхода в списке тредов: чипы «В очереди» (ждут докачки),
  «Недокачано» (на форуме файлов больше, чем сохранено), «Просроченные»
  (парсинг включён, но тред давно не сканировался) и «Мёртвые» (тред выпал из
  каталога форума) со счётчиками; у треда видно причину очереди, дату последней
  попытки, а у мёртвого — дату исчезновения и число промахов; «вернуть в обход»
  сбрасывает `misses` и возвращает тред в публичные списки, «в очередь» —
  ручная постановка на докачку.
- Глобальные операции: «Оптимизировать медиа» (бэкфилл, «осталось N из M»),
  «Очистить S3», «Сбросить всё».
- Добавление раздела: слаг проверяется по каталогу 2ch — если раздел удалён
  (форум отвечает 500/404), создание отклоняется с понятной причиной (в
  `index.json` 2ch остаются удалённые доски, например хентай-разделы `/h`, `/ho`).
- Карточка раздела показывает бейдж «каталог недоступен» с причиной, если
  последнее чтение каталога не удалось (писал парсер или кнопка «Сканировать
  треды»); статус живёт в Redis `board:catalog_error:{slug}`.
- Легаси-страница `/admin/boards/{slug}` (полный список тредов доски) осталась, но
  из UI больше не линкуется — управление тредами доступно в аккордеоне карточки.

## 4. Доступ: роли, метки и премиум

**Матрица ролей**

| Роль | Может | Не может |
|---|---|---|
| Аноним | просмотр доступного контента (включая размытые превью премиума), лента, топ, поиск | метки, скачивание, оригиналы, полные премиум-файлы |
| Зарегистрированный | всё как аноним + метки + размытые превью премиума | скачивание, оригиналы, полные премиум-файлы |
| Премиум | всё как зарегистрированный + премиум-разделы + скачивание + оригиналы | — |

Реализация: `require_user` (метки, профиль) и `require_premium`
(скачивание и оригиналы: аноним → 401, без подписки → 403). Статус подписки —
`users.premium_until`, активация: `POST /api/v1/auth/premium/activate`
(промо, `PROMO_PREMIUM_DAYS = 1`, продление накопительное).

**Правила премиума**
- `boards.is_premium = true` → закрывает **все** треды доски (в админке у тредов
  переключатель PREMIUM блокируется с пометкой «унаследовано от доски»);
- `threads_state.is_premium = true` → закрывает конкретный тред;
- эффективный признак дублируется в `media.is_premium` (синхронизируется при смене
  флагов и проставляется парсером для новых файлов);
- без подписки `GET /api/v1/media/{id}/asset/{thumb|web|video}`, `/raw` и
  `/download` дают **403** (анониму — 401), а `thumb_blur` отдаётся всегда
  (публично, кэшируется);
- в UI: бейдж 🔒 `PREMIUM` + blur + CTA, если подписки нет; бейдж ★ `PREMIUM`
  **без** blur, если подписка активна — видно, где премиум, но нет сигнала «закрыто».

**Метка** (требует аккаунт) — единая пользовательская отметка файла:
- переключатель `POST /api/v1/media/{id}/mark` → `{marked, marks_count}`;
- публичный счётчик `media.marks_count` учитывается в `popularity_score`
  (`views*0.3 + downloads*0.7 + marks*1.5`) и доступен как сортировка `sort=marks`;
- личный список «мои метки» — `GET /api/v1/marks` (страница `/marks`, пункт «Метки»
  в шапке и мобильной навигации, ссылка из профиля);
- отдельного «избранного» нет — оно объединено с метками (миграция `p1q2r3s4t5u6`),
  старый адрес `/favorites` редиректит на `/marks`;
- в интерфейсе: 🏷 метка на карточке и в lightbox, **пробел** — быстрая метка
  в просмотре файла (+ плашка-подтверждение), счётчик меток в профиле.

## 5. Дизайн (кратко)

Полная спека — [`DESIGN.md`](DESIGN.md). Ключевое:
- тёмный «технический» архив: палитра `ink/text/accent`, без теней и градиентов,
  скругления ≤ 4px; данные — JetBrains Mono, интерфейс — Inter;
- логотип `DREDGE` («архив // отбор // доступ»), навигация: Доски / Новинки /
  Популярное / Метки / Поиск (+ мобильная нижняя навигация), аккаунт в шапке;
- бейджи `[ТОП]`, `[PREMIUM]` (🔒 нет доступа / ★ подписка активна), `[НЕДОСТУПНО]`,
  форматы чисел `1.2к` / `1.1М`;
- премиум-превью: бейдж 🔒 `PREMIUM` + blur + CTA, если подписки нет; бейдж
  ★ `PREMIUM` **без** blur, если подписка активна (`is_premium && !locked`) —
  так видно, где премиум-контент, но нет сигнала «закрыто»;
- метка (🏷 тег) — на карточках и в lightbox (пробел в просмотре); маркер видео
  (▶ + длительность) на карточках, превью тредов и в карусели просмотра;
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
  downloads_count, marks_count, popularity_score, created_at, updated_at`
- **view_stats / download_stats**: `media_id, ip_hash, viewed_at/downloaded_at`
  (дедуп статистики по IP за 24 ч)
- **media_marks**: `user_id, media_id, created_at` (UNIQUE user+media) — метка
  «отличный контент»: и публичный счётчик, и личный список «мои метки»;
  счётчик дублируется в `media.marks_count`
- **users**: `id, email, password_hash, is_active, premium_until, created_at`;
  **sessions**: `user_id, token_hash, expires_at`

Значения:
- `download_status`: `new` → `downloaded` (лежит локально, не выгружен) →
  `uploaded` / `verified` (в S3) либо `missing` (файл потерян).
- `media.variants` (JSON): `thumb`, `thumb_blur`, `web` (для видео — `video`)
  → ключи объектов в S3.
- `duplicate_of_id`: файл-ссылка на уже сохранённый оригинал (тот же `md5` в другом
  треде/доске). Дубли не считаются в статистике и не показываются в галереях.
- `marks_count` и `popularity_score`: индекс популярности =
  `views_count * 0.3 + downloads_count * 0.7 + marks_count * 1.5`.

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
n9o0p1q2r3s4  премиум: boards/threads/media.is_premium, users.premium_until
o0p1q2r3s4t5  метки и избранное: media_marks, favorites, media.marks_count
p1q2r3s4t5u6  объединение: favorites → media_marks, удаление таблицы favorites
q2r3s4t5u6v7  threads_state.misses/missing_since (гигиена обхода)
r3s4t5u6v7w8  threads_state.pending_scan/pending_reason/last_scan_attempt_at  ← head
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
GET   /api/v1/media/{id}/raw[?download=1]  оригинал (только премиум: 401/403)
GET   /api/v1/media/{id}/download          отметить скачивание + URL оригинала (премиум)
POST  /api/v1/media/{id}/mark              метка «отличный контент» (переключатель, аккаунт)
GET   /api/v1/marks?page=                  мои метки (аккаунт; /favorites редиректит сюда)
POST  /api/v1/auth/register | /login | /logout
GET   /api/v1/auth/me                      профиль + премиум + счётчик меток
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
GET   /api/v1/admin/boards/{slug}/threads  треды раздела (state: all|active|parsing|visible|premium|queued|lagging|off|dead|stale, q, page)
PATCH /api/v1/admin/boards/{slug}/threads/{id}   флаги треда (+ restore, requeue)
POST  /api/v1/admin/boards/{slug}/threads/bulk   массовые флаги (+ restore, requeue)
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
  `r3s4t5u6v7w8`;
- проверка после выкатки: `X-Cache-Status` у `thumb_blur` (`MISS → HIT`), 403 у
  премиум-`web` без подписки, 401 у `/raw` без сессии;
- обязательные переменные парсера: `DB_COMMIT_EVERY_FILES` (дефолт 25),
  `REQUEST_DELAY`, `PARSE_INTERVAL`, `MAX_FILE_SIZE`, `RECONCILE_MINUTES`;
- резервные копии: `pg_dump` + версионирование бакета S3 (см. `DEPLOY.md`);
- диагностика: застрявшие ключи `parser:progress` / `backfill:variants` со статусом
  `running` после аварийного рестарта → `docker compose exec redis redis-cli del …`.

## 9. Планы

**Ближайшее (эксплуатация)**
1. **Прод-деплой**: домен + SSL (certbot), выкатка compose, мониторинг/uptime,
   ротация `ADMIN_TOKEN`, отзыв старых ключей Backblaze + `git filter-repo`.
2. **Бэкапы БД в S3** по cron (сейчас `pg_dump` руками, см. `DEPLOY.md`) +
   контроль лимитов бакета.

**Парсер (продолжение гигиены обхода — шаги 1–3 сделаны)**
3. Параллельные загрузки (`MAX_PARALLEL_DOWNLOADS`, семафор 2–3): сейчас файлы
   качаются строго последовательно — это главный оставшийся ограничитель скорости.
4. Причина пропуска файла в БД (`threads_state.last_scan_note`), чтобы разбивка
   `[done]` (битых/отфильтровано/ошибок) была видна в админке, а не только в логах.
5. Счётчики очереди/мёртвых/недокачанных на обзорной панели (в карточках разделов) —
   сейчас они только на странице тредов.
6. Инкрементальный проход внутри треда по `last_post_num` — горячие треды не
   проходятся целиком каждый раз.

**Премиум и деньги**
7. Подключить оплату (тарифы/сроки), история активаций (`premium_orders`),
   лимиты и приоритеты для подписчиков.

**Отбор контента**
8. Сортировка «по меткам» в интерфейсе (API `sort=marks` уже поддержан), подборки
   «лучшее за неделю», метки в лентах и на странице доски.

**Медиа**
9. AVIF-превью, HLS/loop-превью видео, CDN перед VPS, прогрев кэша.

**Админка / UX**
10. Кнопка «Убрать дубли» (разовый SQL уже отработан), «выбрать всё по фильтру»,
    конфигурируемый порог «простой парсера».
11. Поиск по темам тредов и slug доски, подсветка, пагинация тредов, закреплённые
    треды, доступность/контраст, LCP.

**Инфраструктура**
12. Логи/ротация, уведомления о лимитах S3, сегментация постгреса при росте,
    второй сервер/очередь (Celery), ИИ-теги.

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
migrations/versions/    alembic-миграции (head: r3s4t5u6v7w8)
web/                    Next.js 14: app/ (страницы), components/, lib/
nginx/nginx.conf        конфиг nginx (прокси + дисковый кэш деривативов)
docker-compose.prod.yml, Dockerfile, .env.example, .env.prod.example
DEPLOY.md               деплой, эксплуатация, диагностика
docs/README.md          этот документ
docs/DESIGN.md          дизайн-спека интерфейса
```
