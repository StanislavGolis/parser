from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # База данных
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/parser"
    
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
    
    class Config:
        env_file = ".env"

settings = Settings()