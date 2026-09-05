# src/services/storage.py
import os
import aiofiles
from pathlib import Path
from typing import Optional
from src.core.config import settings

class StorageService:
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    async def save(self, data: bytes, board_id: int, thread_id: int, filename: str) -> str:
        """Сохраняет файл в локальное хранилище"""
        # Генерируем путь: board_{board_id}/thread_{thread_id}/{filename}
        relative_path = f"board_{board_id}/thread_{thread_id}"
        full_path = self.base_path / relative_path
        full_path.mkdir(parents=True, exist_ok=True)
        
        # Полный путь к файлу
        file_path = full_path / filename
        
        # Сохраняем асинхронно
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(data)
        
        return str(relative_path / filename)
    
    def get_file_path(self, storage_path: str) -> Path:
        """Возвращает полный путь к файлу"""
        return self.base_path / storage_path
    
    async def delete(self, storage_path: str):
        """Удаляет файл из хранилища"""
        file_path = self.get_file_path(storage_path)
        if file_path.exists():
            os.remove(file_path)
    
    async def exists(self, storage_path: str) -> bool:
        """Проверяет существование файла"""
        return self.get_file_path(storage_path).exists()