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

    # Backblaze B2
    B2_KEY_ID: str = ""
    B2_APPLICATION_KEY: str = ""
    B2_BUCKET_NAME: str = ""
    B2_ENDPOINT: str = "https://s3.us-west-000.backblazeb2.com"
    B2_SIGNED_URL_TTL: int = 3600  # срок жизни подписанного URL в секундах (1 час)
    
    class Config:
        env_file = ".env"

settings = Settings()