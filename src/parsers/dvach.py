# src/parsers/dvach.py
import aiohttp
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
import hashlib
import re
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.models import Board, Thread, MediaFile
from src.repositories.board_repo import BoardRepository
from src.repositories.thread_repo import ThreadRepository
from src.repositories.media_repo import MediaRepository
from src.services.downloader import DownloaderService
from src.services.storage import StorageService
from src.services.media_validator import MediaValidator
from src.services.b2_uploader import B2Uploader

class DvachParser:
    """Парсер для 2ch.hk (Dvach)"""
    
    BASE_URL = "https://2ch.hk"
    API_URL = "https://2ch.hk/api"
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.board_repo = BoardRepository(session)
        self.thread_repo = ThreadRepository(session)
        self.media_repo = MediaRepository(session)
        self.downloader = DownloaderService()
        self.storage = StorageService(settings.STORAGE_PATH)
        self.b2_uploader = B2Uploader()
        
        self.http_session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.http_session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.http_session:
            await self.http_session.close()
    
    async def parse_board(self, board_slug: str) -> List[Dict]:
        """Парсит доску и возвращает список тредов"""
        url = f"{self.BASE_URL}/{board_slug}/"
        
        try:
            async with self.http_session.get(url) as response:
                response.raise_for_status()
                html = await response.text()

                print(f"   HTML получен, длина: {len(html)}")
                
                # Ищем все ссылки на треды
                # <a href="/b/res/123456.html" class="thread-link">
                pattern = r'href="/([^/]+)/res/(\d+)\.html"'
                matches = re.findall(pattern, html)

                print(f"   Найдено ссылок на треды: {len(matches)}")
                
                threads = []
                for board, thread_id in matches:
                    if board == board_slug:  # Только нужная доска
                        threads.append({
                            'board': board_slug,
                            'thread_id': int(thread_id),
                            'url': f"{self.BASE_URL}/{board}/res/{thread_id}.html"
                        })
                
                return threads
                
        except Exception as e:
            print(f"Ошибка при парсинге доски /{board_slug}: {e}")
            return []
    
    async def parse_thread(self, board_slug: str, thread_id: int) -> List[Dict]:
        """Парсит конкретный тред и возвращает список постов с медиа"""
        url = f"{self.BASE_URL}/{board_slug}/res/{thread_id}.html"
        
        try:
            async with self.http_session.get(url) as response:
                response.raise_for_status()
                html = await response.text()
                
                # Отладочный вывод
                print(f"      Парсим тред {thread_id}, длина HTML: {len(html)}")
                
                # Ищем ссылки на файлы в формате /b/src/123456789.jpg
                # или /b/src/123456789.mp4
                pattern = r'<a[^>]+href="/([^/"]+)/src/([^"]+)"[^>]*>'
                matches = re.findall(pattern, html)
                
                print(f"      Найдено ссылок на файлы: {len(matches)}")
                
                posts = []
                for board, filename in matches:
                    # Проверяем, что это нужная доска и файл имеет расширение
                    if board == board_slug and '.' in filename:
                        # Проверяем расширение
                        ext = filename.split('.')[-1].lower()
                        if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'mp4', 'webm', 'mkv']:
                            file_url = f"{self.BASE_URL}/{board}/src/{filename}"
                            posts.append({
                                'thread_id': thread_id,
                                'file_url': file_url,
                                'filename': filename,
                            })
                
                if posts:
                    print(f"      Найдено медиафайлов в треде: {len(posts)}")
                
                return posts
                
        except Exception as e:
            print(f"      Ошибка при парсинге треда {thread_id}: {e}")
            return []
    
    async def process_board(self, board_slug: str):
        """Полный цикл обработки доски"""
        print(f"🔍 Начинаем парсинг доски /{board_slug}")
        
        # 1. Получаем или создаем доску в БД
        board, created = await self.board_repo.get_or_create(
            slug=board_slug,
            defaults={'name': board_slug.upper(), 'is_active': True}
        )
        
        # 2. Получаем список тредов
        threads_data = await self.parse_board(board_slug)
        print(f"   Найдено {len(threads_data)} тредов")
        
        # 3. Для каждого треда проверяем новые посты
        for thread_data in threads_data:
            thread_id = thread_data['thread_id']
            
            # Проверяем, есть ли тред в БД
            thread, _ = await self.thread_repo.get_or_create(
                board_id=board.id,
                thread_id=thread_id,
                defaults={'is_active': True}
            )
            
            # Парсим посты в треде
            posts = await self.parse_thread(board_slug, thread_id)
            
            # 4. Скачиваем медиа из постов
            for post in posts:
                await self.process_post(board.id, thread.id, thread_id, post)
            
            # Задержка между тредами
            await asyncio.sleep(settings.REQUEST_DELAY)
        
        # Обновляем время последнего парсинга
        board.last_parsed_at = datetime.utcnow()
        await self.session.flush()
        await self.session.commit()
        
        print(f"✅ Парсинг доски /{board_slug} завершен")
    
    async def process_post(self, board_id: int, thread_id: int, thread_external_id: int, post: Dict):
        """Обработка одного поста - скачивание, валидация, загрузка в B2 и сохранение в БД"""
        file_url = post['file_url']
        filename = post['filename']
        
        # Извлекаем имя файла без пути
        if '/' in filename:
            filename = filename.split('/')[-1]
        
        try:
            # 1. Скачиваем файл
            print(f"   📥 Скачиваем: {filename}")
            file_data = await self.downloader.download(file_url)
            
            if not file_data:
                print(f"   ❌ Не удалось скачать: {filename}")
                return
            
            # 2. Валидация файла
            is_valid, error, metadata = MediaValidator.validate(file_data, filename)
            if not is_valid:
                print(f"   🚫 Отфильтрован: {filename} — {error}")
                return
            
            # 3. Проверка дубликата по хешу
            is_dup, file_hash = MediaValidator.is_duplicate(file_data)
            if is_dup:
                existing = await self.media_repo.get_by_hash(file_hash)
                if existing:
                    print(f"   ⏭️ Дубликат: {filename} (уже есть ID: {existing.id})")
                    return
            
            # 4. Определяем тип файла
            file_type = metadata.get('file_type', 'image')
            mime_type = metadata.get('mime_type', 'application/octet-stream')
            
            # 5. Сохраняем в локальное хранилище
            storage_path = await self.storage.save(
                file_data, 
                board_id=board_id,
                thread_id=thread_external_id,
                filename=filename
            )
            
            # 6. Загружаем в Backblaze B2 (приватный бакет)
            remote_key = f"board_{board_id}/thread_{thread_external_id}/{filename}"
            b2_key = await self.b2_uploader.upload_file(
                self.storage.get_file_path(storage_path),
                remote_key
            )
            
            # 7. Удаляем локальный файл, если загружен в B2
            local_file_deleted = False
            if b2_key:
                try:
                    local_file = self.storage.get_file_path(storage_path)
                    if local_file.exists():
                        import os
                        os.remove(local_file)
                        local_file_deleted = True
                        print(f"   🗑️ Локальный файл удален: {filename}")
                except Exception as e:
                    print(f"   ⚠️ Не удалось удалить локальный файл: {e}")
            
            # 8. Сохраняем в БД
            media_data = {
                'board_id': board_id,
                'thread_id': thread_id,
                'thread_external_id': thread_external_id,
                'post_external_id': post.get('post_id', 0),
                'original_filename': filename,
                'file_hash': file_hash,
                'file_size': len(file_data),
                'storage_path': storage_path if not local_file_deleted else None,
                'file_type': file_type,
                'mime_type': mime_type,
                'width': metadata.get('width'),
                'height': metadata.get('height'),
                'b2_key': b2_key,
                'status': 'uploaded' if b2_key else 'downloaded'
            }
            
            media = await self.media_repo.create(**media_data)
            
            if b2_key:
                print(f"   ✅ Загружен в B2: {filename} (ID: {media.id})")
            else:
                print(f"   ⚠️ Файл сохранен локально: {filename} (ID: {media.id})")
            
        except Exception as e:
            print(f"   ❌ Ошибка при обработке {filename}: {e}")