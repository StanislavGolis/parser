# src/main.py
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Добавляем путь к проекту
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.config import settings
from src.parsers.dvach import DvachParser


async def init_db():
    """Создаёт движок и фабрику async-сессий.

    Схема БД управляется Alembic (`alembic upgrade head`); create_all не используется.
    """
    engine = create_async_engine(settings.DATABASE_URL, echo=True, future=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return async_session


async def main():
    print("🚀 Запуск парсера...")
    print(f"📁 Хранилище: {settings.STORAGE_PATH}")
    print(f"📋 Доски: {', '.join(settings.BOARDS_TO_PARSE)}")
    print("-" * 50)

    async_session = await init_db()
    last_reconcile: Optional[datetime] = None

    while True:
        try:
            async with async_session() as session:
                parser = DvachParser(session)
                await parser.__aenter__()
                try:
                    # Сверка данных при первом старте
                    if last_reconcile is None:
                        await parser.run_reconciliation()
                        last_reconcile = datetime.utcnow()

                    # Парсим все доски
                    for board_slug in settings.BOARDS_TO_PARSE:
                        await parser.process_board(board_slug)
                finally:
                    await parser.__aexit__(None, None, None)

            # Периодическая сверка
            if (
                settings.RECONCILE_MINUTES > 0
                and last_reconcile
                and (datetime.utcnow() - last_reconcile).total_seconds() / 60 >= settings.RECONCILE_MINUTES
            ):
                async with async_session() as session:
                    parser = DvachParser(session)
                    await parser.__aenter__()
                    try:
                        await parser.run_reconciliation()
                    finally:
                        await parser.__aexit__(None, None, None)
                last_reconcile = datetime.utcnow()

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