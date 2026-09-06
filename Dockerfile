# ─────────────────────────────────────────────────────────────────
#  Backend-образ для сервисов parser / api / migrate.
#  Сборка из корня репозитория:  docker build -t parser-backend .
# ─────────────────────────────────────────────────────────────────

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# libmagic — обязателен для python-magic (валидация MIME),
# curl — для healthcheck в docker compose.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
