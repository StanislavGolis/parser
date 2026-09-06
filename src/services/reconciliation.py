# src/services/reconciliation.py
"""Сверка данных БД с реальным состоянием хранилищ (локальный кэш, Backblaze B2).

Задачи:
- записи со статусом downloaded/new без локального файла → missing;
- записи с загруженным в B2 файлом, у которых осталась локальная копия → очистка кэша;
- осиротевшие файлы в storage/ (нет записи в БД) → удаление;
- если B2 настроен (полная сверка):
  - объекты B2 сверяются со media.b2_key (отсутствующие → перезаливка или missing);
  - записи downloaded с локальным файлом → выгрузка в B2.
"""
from pathlib import Path
from typing import List, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import Media
from src.repositories.media_repo import MediaRepository
from src.services.b2_uploader import B2Uploader
from src.services.storage import StorageService

UPLOADED_STATUSES = {"uploaded", "verified"}


class ReconciliationService:
    def __init__(self, session: AsyncSession, storage: StorageService, b2_uploader: B2Uploader):
        self.session = session
        self.storage = storage
        self.b2 = b2_uploader
        self.media_repo = MediaRepository(session)

    async def run(self) -> None:
        """Основной цикл сверки."""
        await self._reconcile_local()
        if self.b2.is_configured:
            await self._reconcile_b2()
        await self.session.commit()
        print("   ✅ Сверка данных (БД ↔ хранилище) завершена")

    # ─────────────── Локальный кэш ───────────────

    async def _load_all_media(self) -> List[Media]:
        result = await self.session.execute(select(Media))
        return list(result.scalars().all())

    async def _reconcile_local(self) -> None:
        media_list = await self._load_all_media()
        known_paths: Set[str] = {m.local_path for m in media_list if m.local_path}

        # 1. Осиротевшие файлы в локальном кэше (нет записи в БД)
        if self.storage.base_path.exists():
            for file_path in self.storage.base_path.rglob("*"):
                if not file_path.is_file():
                    continue
                rel = file_path.as_posix().removeprefix(self.storage.base_path.as_posix() + "/")
                if rel not in known_paths:
                    try:
                        file_path.unlink()
                        print(f"   🧹 Удалён осиротевший локальный файл: {rel}")
                    except OSError as e:
                        print(f"   ⚠️ Не удалось удалить {rel}: {e}")

        # 2. Записи без локального файла и без B2 → missing
        for m in media_list:
            if m.download_status in ("new", "downloaded") and not m.b2_key:
                if not m.local_path or not self.storage.get_file_path(m.local_path).exists():
                    if m.download_status != "missing":
                        m.download_status = "missing"
                        print(f"   🗑  Файл не найден локально, статус → missing (media #{m.id}): {m.original_name}")

        # 3. Лишние локальные копии уже загруженных в B2 файлов
        for m in media_list:
            if m.download_status in UPLOADED_STATUSES and m.local_path:
                p = self.storage.get_file_path(m.local_path)
                if p.exists():
                    try:
                        p.unlink()
                        print(f"   🧹 Удалена локальная копия залитого файла: {m.local_path}")
                    except OSError as e:
                        print(f"   ⚠️ Не удалось удалить {m.local_path}: {e}")

    # ─────────────── Объектное хранилище (B2) ───────────────

    async def _reconcile_b2(self) -> None:
        keys = await self.b2.list_keys()
        if keys is None:
            print("   ⚠️ Не удалось получить список объектов B2, B2-сверка пропущена")
            return
        key_set = set(keys)

        media_list = await self._load_all_media()
        for m in media_list:
            if m.b2_key:
                if m.b2_key in key_set:
                    if m.download_status != "verified":
                        m.download_status = "verified"
                        print(f"   ✅ B2 подтверждён (media #{m.id}): {m.original_name}")
                else:
                    # Объект пропал из B2 — перезаливаем или помечаем missing
                    local_file = self.storage.get_file_path(m.local_path) if m.local_path else None
                    if local_file and local_file.exists():
                        print(f"   🔄 Перезаливаю в B2 (media #{m.id}): {m.original_name}")
                        file_id = await self.b2.upload_file(local_file, m.b2_key)
                        m.download_status = "uploaded" if file_id else "missing"
                    else:
                        m.download_status = "missing"
                        print(f"   ❌ Объект B2 не найден и локальной копии нет (media #{m.id}): {m.original_name}")
            else:
                # Нет b2_key — выгружаем, если есть локальный файл
                if m.download_status in ("new", "downloaded") and m.local_path:
                    local_file = self.storage.get_file_path(m.local_path)
                    if local_file.exists():
                        remote_key = f"board_{m.board_id}/thread_{m.thread_id}/{Path(m.local_path).name}"
                        file_id = await self.b2.upload_file(local_file, remote_key)
                        if file_id:
                            m.b2_key = remote_key
                            m.download_status = "uploaded"
                            print(f"   📤 Выгружен в B2 (media #{m.id}): {m.original_name}")