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

    # Сверка данных (reconciliation)
    RECONCILE_MINUTES: int = 60  # период сверки БД ↔ хранилище, 0 = только при старте

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