# SLUICE

Медиа-архив/галерея: парсит медиа с разделов форума (2ch), скачивает и архивирует
в объектное хранилище S3 (Timeweb Cloud), каталогизирует и публикует на сайте —
каталог «досок» → треды → файлы с техпанелью, новинки, топ, поиск, аккаунты и
премиум-подписка (размытые превью + активация в профиле).

## Стек

- **Backend**: Python 3.11, FastAPI, SQLAlchemy 2 (async), Alembic, boto3 (S3),
  Pillow + ffmpeg (деривативы), Redis (rate limiting, прогресс парсера).
- **Frontend**: Next.js 14 (App Router), TypeScript, Tailwind; тёмная
  «техническая» дизайн-система.
- **Инфраструктура**: Docker Compose (postgres, redis, migrate, parser, api, web,
  nginx), nginx как точка входа с дисковым кэшем деривативов.

## Быстрый старт

```bash
cp .env.prod.example .env      # заполнить S3_* и ADMIN_TOKEN
docker compose -f docker-compose.prod.yml up -d --build
# сайт:    http://localhost:80
# админка: http://localhost/admin   (ADMIN_TOKEN из .env, хранится в sessionStorage)
```

Разработка без контейнеров:

```bash
# postgres/redis — в Docker; затем:
pip install -r requirements.txt
uvicorn src.api.main:app --reload          # API на :8000
python src/main.py                         # парсер (демон)
cd web && npm install && npm run dev       # фронт на :3000
```

## Документация

- [`docs/README.md`](docs/README.md) — техническая документация: статус,
  архитектура, модули, доступ (аккаунты/премиум), БД, миграции, полный список API.
- [`docs/DESIGN.md`](docs/DESIGN.md) — дизайн-спека интерфейса.
- [`DEPLOY.md`](DEPLOY.md) — деплой на VPS: SSL, проверка после выкатки,
  диагностика (застрявшие ключи, дубли, место на диске), бэкапы, переменные окружения.

## Что важно знать

- Парсер идемпотентен: повторный проход не размножает записи, уже сохранённые файлы
  пропускаются; коммит БД — после треда и каждые `DB_COMMIT_EVERY_FILES` файлов.
- Премиум закрывает контент целиком (доска/тред): полные версии и оригиналы — по
  подписке, публично — только размытый `thumb_blur`; премиум-ответы не кэшируются.
- Статистика «файлов / в S3 / видимых» не считает дубли-ссылки — совпадает с сайтом.
- Общий образ `parser-backend:local` собирается сервисом `api`:
  `up -d --build parser` код не обновляет (см. `DEPLOY.md` §Диагностика).
