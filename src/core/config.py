from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # База данных
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/parser"

    # Redis (кэш, rate limiting, счётчики)
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Хранилище
    STORAGE_PATH: str = "./storage/media"
    
    # Парсинг
    PARSE_INTERVAL: int = 30  # секунд
    BOARDS_TO_PARSE: list[str] = ["b", "pr", "sci"]
    
    # Ограничения
    MAX_FILES_PER_POST: int = 5
    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100 MB
    
    # Задержки для защиты от бана
    REQUEST_DELAY: float = 0.5  # секунд между запросами

    # Коммит БД каждые N файлов внутри треда: файлы становятся видны на сайте
    # по мере скачивания, а сбой теряет максимум N файлов (0 — коммит только
    # после треда, как было раньше).
    DB_COMMIT_EVERY_FILES: int = 25

    # Сверка данных (reconciliation)
    RECONCILE_MINUTES: int = 60  # период сверки БД ↔ хранилище, 0 = только при старте

    # Гигиена обхода тредов (чтобы не было «забытых» тредов)
    DEAD_THREAD_AFTER_MISSES: int = 3  # столько проходов каталога подряд без треда → is_active=False
    STALE_SCAN_HOURS: int = 24         # тред не сканировался дольше → «просрочен» (чип в админке)
    # Бюджет цикла: после N минут фаза B прерывается, а остаток очереди
    # продолжается в следующем цикле (0 — без ограничения, гнать до конца очереди)
    PARSE_CYCLE_BUDGET_MINUTES: int = 30

    # Параллельные загрузки внутри треда: сколько файлов тянуть с форума
    # одновременно (1 — строго последовательно, как раньше). Параллелится только
    # скачивание; валидация, S3 и запись в БД всегда последовательны.
    MAX_PARALLEL_DOWNLOADS: int = 2
    # Ограничение памяти под «предзагрузку» пачки файлов: крупные файлы качаются
    # по одному, чтобы не держать в RAM сотни мегабайт
    PREFETCH_MAX_BYTES: int = 64 * 1024 * 1024
    # Параллельная выгрузка в S3 внутри треда. По умолчанию 1: замер на нашем
    # S3-эндпоинте показал, что одновременные загрузки в 3 раза МЕДЛЕННЕЕ
    # (3.0 МБ/с против 10.9 МБ/с при 8 МБ объектах) — хранилище троттлит
    # соединения. Значение >1 имеет смысл только после замера на своём эндпоинте
    # (комментарий в README §3.1, конвейер: подготовка → S3 → БД).
    MAX_PARALLEL_UPLOADS: int = 1

    # Логировать SQL-запросы (echo у SQLAlchemy). В прод — выключено: парсер
    # печатает каждый запрос, логи растут на гигабайты. Включать только для отладки.
    SQL_ECHO: bool = False
    # Cookie сессии только по HTTPS (в проде за SSL — включить). Локально без
    # сертификата оставить false, иначе браузер не сохранит cookie.
    SESSION_COOKIE_SECURE: bool = False

    # API сайта
    ADMIN_TOKEN: str = ""                     # токен для админ-эндпоинтов
    API_RATE_LIMIT: int = 30                  # запросов в минуту на IP (публичные API)
    API_CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8080"
    POPULARITY_RECALC_MINUTES: int = 5        # период пересчёта popularity_score, в минутах

    # ── Объектное хранилище S3 (Timeweb Cloud) ────────────────────
    # Значения из панели Timeweb: S3 URL, бакет, Access/Secret Key, регион.
    S3_URL: str = "https://s3.twcstorage.ru"
    S3_REGION: str = "ru-1"
    S3_BUCKET: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_ADDRESSING_STYLE: str = "path"  # имя бакета — UUID: используем path-style
    S3_SIGNED_URL_TTL: int = 3600      # срок жизни presigned-URL (резервный режим)

    # Отдача медиа: proxy — через API (бакет не раскрывается клиенту); presigned — прямые ссылки
    MEDIA_DELIVERY: str = "proxy"

    @property
    def storage_endpoint(self) -> str:
        return self.S3_URL or "https://s3.twcstorage.ru"

    @property
    def storage_region(self) -> str:
        return self.S3_REGION or "ru-1"

    @property
    def storage_bucket(self) -> str:
        return self.S3_BUCKET

    @property
    def storage_access_key(self) -> str:
        return self.S3_ACCESS_KEY

    @property
    def storage_secret_key(self) -> str:
        return self.S3_SECRET_KEY
    
    class Config:
        env_file = ".env"
        extra = "ignore"  # не падать из-за «лишних» переменных в .env

settings = Settings()