# src/main.py
import asyncio
import sys
from pathlib import Path

# Добавляем путь к проекту
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.core.config import settings
from src.core.models import Base
from src.parsers.dvach import DvachParser

async def init_db():
    """Инициализация БД"""
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=True,
        future=True
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    return async_session

async def main():
    print("🚀 Запуск парсера...")
    print(f"📁 Хранилище: {settings.STORAGE_PATH}")
    print(f"📋 Доски: {', '.join(settings.BOARDS_TO_PARSE)}")
    print("-" * 50)
    
    # Инициализируем БД
    async_session = await init_db()
    
    while True:
        try:
            async with async_session() as session:
                parser = DvachParser(session)
                await parser.__aenter__()
                
                # Парсим все доски
                for board_slug in settings.BOARDS_TO_PARSE:
                    await parser.process_board(board_slug)
                
                await parser.__aexit__(None, None, None)
            
            print(f"\n⏳ Ожидание {settings.PARSE_INTERVAL} секунд до следующего цикла...\n")
            await asyncio.sleep(settings.PARSE_INTERVAL)
            
        except KeyboardInterrupt:
            print("\n👋 Остановка парсера...")
            break
        except Exception as e:
            print(f"❌ Критическая ошибка: {e}")
            await asyncio.sleep(5)  # Пауза перед перезапуском

if __name__ == "__main__":
    asyncio.run(main())