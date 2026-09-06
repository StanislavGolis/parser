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
- `B2_*` — если заполнены, API генерирует presigned URL, парсер заливает файлы в бакет;
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
- Медиа раздаётся браузеру напрямую из Backblaze B2 по временным presigned URL
  (срок `B2_SIGNED_URL_TTL`, по умолчанию 1 час).
- Если B2 не настроен — парсер складывает файлы в том `media`, а сайт
  показывает заглушки вместо превью (функционал API сохраняется).
