# SLUICE — Техническое и дизайнерское ТЗ (v4)

> SLUICE — медиа-архив / галерея / доступ: автоматически парсит медиа с разделов
> форума (2ch), скачивает и архивирует в объектное хранилище S3 (Timeweb Cloud), каталогизирует и показывает
> на сайте: каталог «досок», внутри — треды («папки»), файлы с техпанелью,
> приватные разделы по коду, поиск, топ. Тёмный «технический» интерфейс.
>
> Единый документ: технические требования + текущий статус + планы.
> Полный дизайн-документ: [`docs/DESIGN.md`](docs/DESIGN.md).

---

## 1. Текущий статус

**Реализовано:**
- [x] 1–2. Парсер 2ch на JSON API: полный и инкрементальный цикл, дедуп по `md5`
      до скачивания, фильтры (размер/разрешение/MIME), SHA-256, загрузка в S3
      (boto3/S3) с корректным Content-Type, reconciliation БД ↔ хранилище.
- [x] 3. Схема БД v3 + Alembic; 3.1 reconciliation; 3.2 — доработки по ходу тестов
      (коммит по тредам, предсоздание досок, метаданные тредов).
- [x] 4. Объектное хранилище S3 (Timeweb Cloud, приватный бакет; отдача через API-прокси).
- [x] 5. Backend FastAPI: REST API, rate limiting на Redis, admin-токен, статистика
      просмотров/скачиваний, пересчёт популярности.
- [x] 6. Frontend Next.js: главная «Доски», новинки, доска→треды, карточки медиа,
      lightbox с MD5/SHA-256, топ, поиск, приватный вход, мобильная навигация.
- [x] 6.1. Дизайн-система SLUICE (этапы UI 1–4): токены, шрифты JetBrains Mono/Inter,
      админка приведена к токенам.
- [x] 7. Production-стек Docker Compose (локально «в один клик»), Nginx; деплой на VPS — **не выполнен**.
- [x] Админ-центр управления контентом: парсер-демон с кнопками запуска/остановки,
      очередь парсинга, переименование/удаление разделов (БД + S3), «очистка S3»,
      полный сброс, доски форума из `index.json`.

**Известные ограничения:**
- Исходящий трафик S3 (Timeweb Cloud) тарифицируется; медиа проксируется через VPS,
  поэтому при большом трафике стоит добавить кэш (nginx) — см. план S3 (nginx-кэш).
- Превью видео — браузерный кадр (`preload=metadata`); ffmpeg-кадры и длительность
  — в планах.

## 2. Архитектура

Один VPS (Docker Compose): `postgres`, `redis`, `migrate`, `parser`, `api`, `web`, `nginx`.
Наружу — только `nginx`; медиа отдаёт API (прокси S3 — бакет клиенту не раскрывается).

Запуск продакшен-стека (локально = как на VPS):

```bash
docker compose -f docker-compose.prod.yml up -d --build   # поднимет всё
# сайт: http://localhost:${HTTP_PORT:-80}
```

Локальная разработка без контейнеров: `postgres`/`redis` в Docker (dev-compose),
API — `uvicorn src.api.main:app --reload`, парсер — `python src/main.py`,
фронт — `cd web && npm run dev`.

## 3. Модули

### 3.1 Парсер (src/main.py, src/parsers)
- Демон: контейнер всегда запущен, парсинг включается флагом `parser:enabled`
  (кнопка в админке); heartbeat `parser:up/alive/current_board` в Redis;
- доски для парсинга берутся из БД (`boards.parse_enabled`, порядок `sort_order`);
- инкрементальный проход тредов, коммит по каждому треду; стоп между файлами/тредами;
- метаданные тредов (`subject/comment/timestamp`) сохраняются из каталога;
- фильтрация до скачивания, валидация, Content-Type при upload в S3.

### 3.2 API (src/api)
- Публичные роуты: boards, board threads, media (список/деталь/view/download), feed,
  top, search, access (код приватной доски → httpOnly-cookie 24 ч);
- админ-роуты (admin-токен): overview, форум-доски (index.json), board CRUD,
  reorder, delete, parser start/stop, cleanup-storage, reset;
- rate limiting на Redis, потоковая отдача медиа из S3 через `S3Storage.open_object_stream`.

### 3.3 Frontend (web/, Next.js 14 App Router)
- Главная = каталог досок со статусами и фильтрами; `/new` (новинки), `/top`,
  `/board/{slug}` (треды), `/search`, `/media/{id}`;
- карточки медиа (фото/видео) с graceful-fallback, lightbox с MD5/SHA-256;
- приватные разделы: замок в каталоге → экран кода → доступ 24 ч (cookie);
- дизайн-система SLUICE — см. `docs/DESIGN.md`.

### 3.4 Админ-панель (/admin)
- Кнопки «Запустить/Остановить парсер», очередь парсинга (▲/▼);
- «Мои разделы»: переключатели Парсить/На сайте/По коду, поле кода у каждой доски,
  переименование, удаление, статистика (в БД/S3/пропущено/треды), polling;
- «Доски форума»: весь список 2ch с поиском и добавлением;
- «Очистить S3», «Сбросить всё» (БД + S3, сначала останавливает парсер).
## 4. Дизайн (кратко)

Полная дизайн-спека: **`docs/DESIGN.md`**. Ключевое:
- тёмный «технический» архив: палитра `ink/text/accent`, без теней/градиентов,
  скругления ≤ 4px; моноширинные данные (JetBrains Mono) + Inter;
- логотип `SLUICE`, навигация: Доски / Новинки / Популярное / Поиск
  (+ нижняя мобильная навигация);
- бейджи-статусы `[ПРИВАТНАЯ]`, `[ТОП]`, `[НЕДОСТУПНО]`; формат чисел `1.2к`.

## 5. База данных (PostgreSQL, Alembic)

- **boards**: `id, slug, title, description, is_visible, parse_enabled, is_private,
  access_code_hash, sort_order, created_at, updated_at`
- **threads_state**: `board_id, thread_id, subject, comment, thread_timestamp,
  posts_count, files_count, last_scanned_at, is_active` (unique board+thread)
- **media**: `id, board_id, thread_id, original_name, source_url, file_hash (sha-256),
  source_md5, file_size, mime_type, media_type(image|video), s3_bucket, s3_key,
  local_path, width, height, download_status(new|downloaded|uploaded|verified|missing),
  is_visible, duplicate_of_id, is_active, views_count, downloads_count,
  popularity_score, created_at, updated_at`
- **view_stats / download_stats**: дедуп по `ip_hash` за 24 ч.

## 6. REST API (актуально)

```
GET   /api/v1/boards                       доски (вкл. приватные, is_private)
GET   /api/v1/boards/{slug}/threads        треды доски (метаданные + статистика + превью)
GET   /api/v1/boards/{slug}/media          файлы доски (?thread=, ?sort=, ?type=)
POST  /api/v1/boards/{slug}/access         код доступа (=> httpOnly-cookie ba_{slug}, 24 ч)
GET   /api/v1/media/{id} | /view | /download | /raw   (raw — поток S3 без раскрытия бакета)
GET   /api/v1/feed?type=&page=             новинки (без приватных)
GET   /api/v1/top?type=&period=&limit=     топ день/неделя/месяц (без приватных)
GET   /api/v1/search?q=                    поиск: имя файла / md5 / sha-256
GET   /healthz
# админ (Bearer admin-токен):
GET   /api/v1/admin/overview               сводка: доски + статистика + статус парсера
GET   /api/v1/admin/forum                  все доски форума (index.json 2ch)
GET   /api/v1/admin/boards                 доски с флагами/статистикой
POST  /api/v1/admin/boards                 создать по slug (+name)
PATCH /api/v1/admin/boards/{slug}          флаги / title / код
DELETE /api/v1/admin/boards/{slug}         удалить раздел (БД + файлы S3)
POST  /api/v1/admin/boards/reorder         порядок очереди парсинга
GET   /api/v1/admin/boards/{slug}/threads  треды раздела (для админки)
POST  /api/v1/admin/parser/start|stop      управление парсером
POST  /api/v1/admin/cleanup-storage             удалить объекты S3 без записей в БД
DELETE /api/v1/admin/reset                 полный сброс (БД + S3), парсер ставится на паузу
```

## 7. Деплой (этап 7)

- `docker-compose.prod.yml` + `nginx/nginx.conf` + `Dockerfile` — готовы и проверены локально;
- на VPS: `git clone`, `cp .env.prod.example .env`, заполнить, `docker compose -f docker-compose.prod.yml up -d --build`;
- далее: домен → SSL (certbot/nginx), опционально Cloudflare CDN.
- подробнее: `DEPLOY.md`.

## 8. Планы на ближайшую разработку

1. **Деплой на VPS**: домен + SSL + сертификаты; выкатка compose; мониторинг.
2. **Медиа**: ffmpeg в парсере — кадр-превью видео + длительность (бейдж `0:42`);
   опционально мини-превью WebP; прогрев/ре-рендер старых файлов.
3. **Поиск**: расширение — по темам тредов, slug доски, фильтр типа; подсветка.
4. **UX-полировка**: вкладки/фильтры в общем стиле (остатки нейтральных классов),
   пагинация/бесконечная лента тредов, доступность/контраст, LCP.
5. **Эксплуатация**: бэкапы БД в S3, логи/ротация, uptime-мониторинг, уведомления о
   лимитах S3 (превью/«недоступно»).
6. **Опции**: Cloudflare CDN, Celery/очереди, ИИ-теги, второй сервер.

## 9. Структура репозитория

```
src/            python-бэкенд (main, parsers, services, repositories, api)
migrations/     alembic
web/            Next.js (страницы, компоненты, lib)
nginx/          конфиг nginx
docker-compose.prod.yml, Dockerfile, .env.prod.example
DEPLOY.md       инструкция по деплою
docs/DESIGN.md  дизайн-спека
```

---
КОНЕЦ ТЗ v4

