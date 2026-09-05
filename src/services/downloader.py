# src/services/downloader.py
import aiohttp
import asyncio
from typing import Optional
from src.core.config import settings

class DownloaderService:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.semaphore = asyncio.Semaphore(10)  # Ограничение параллельных загрузок
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def download(self, url: str) -> Optional[bytes]:
        """Скачивает файл с ограничением размера"""
        async with self.semaphore:
            try:
                # Заголовки чтобы не заблокировали
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                
                async with self.session.get(url, headers=headers) as response:
                    response.raise_for_status()
                    
                    # Проверяем размер
                    content_length = response.headers.get('Content-Length')
                    if content_length and int(content_length) > settings.MAX_FILE_SIZE:
                        print(f"   ⚠️ Файл слишком большой: {url}")
                        return None
                    
                    # Скачиваем с ограничением по времени
                    data = await asyncio.wait_for(
                        response.read(),
                        timeout=30  # 30 секунд
                    )
                    
                    return data
                    
            except asyncio.TimeoutError:
                print(f"   ⏱️ Таймаут при скачивании: {url}")
                return None
            except Exception as e:
                print(f"   ❌ Ошибка при скачивании {url}: {e}")
                return None