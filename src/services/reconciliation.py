# src/services/reconciliation.py
"""Сверка данных БД с реальным состоянием хранилищ (локальный кэш, S3 Timeweb Cloud).

Задачи:
- записи со статусом downloaded/new без локального файла → missing;
- записи с загруженным в S3 файлом, у которых осталась локальная копия → очистка кэша;
- осиротевшие файлы в storage/ (нет записи в БД) → удаление;
- если S3 настроен (полная сверка):
  - объекты S3 сверяются со media.s3_key (отсутствующие → перезаливка или missing);
  - записи downloaded с локальным файлом → выгрузка в S3.
"""
from pathlib import Path
from typing import List, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import Media
from src.repositories.media_repo import MediaRepository
from src.services.s3_storage import S3Storage
from src.services.storage import StorageService

UPLOADED_STATUSES = {"uploaded", "verified"}


class ReconciliationService:
    def __init__(self, session: AsyncSession, storage: StorageService, s3_storage: S3Storage):
        self.session = session
        self.storage = storage
        self.s3 = s3_storage
        self.media_repo = MediaRepository(session)

    async def run(self) -> None:
        """Основной цикл сверки."""
        await self._reconcile_local()
        if self.s3.is_configured:
            await self._reconcile_storage()
        await self.session.commit()
        print("   [ok] Сверка данных (БД ↔ хранилище) завершена")

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
                        print(f"   [clean] Удалён осиротевший локальный файл: {rel}")
                    except OSError as e:
                        print(f"   [warn] Не удалось удалить {rel}: {e}")

        # 2. Записи без локального файла и без S3 → missing
        for m in media_list:
            if m.download_status in ("new", "downloaded") and not m.s3_key:
                if not m.local_path or not self.storage.get_file_path(m.local_path).exists():
                    if m.download_status != "missing":
                        m.download_status = "missing"
                        print(f"   [del]  Файл не найден локально, статус → missing (media #{m.id}): {m.original_name}")

        # 3. Лишние локальные копии уже загруженных в S3 файлов
        for m in media_list:
            if m.download_status in UPLOADED_STATUSES and m.local_path:
                p = self.storage.get_file_path(m.local_path)
                if p.exists():
                    try:
                        p.unlink()
                        print(f"   [clean] Удалена локальная копия залитого файла: {m.local_path}")
                    except OSError as e:
                        print(f"   [warn] Не удалось удалить {m.local_path}: {e}")

    # ─────────────── Объектное хранилище (S3) ───────────────

    async def _reconcile_storage(self) -> None:
        keys = await self.s3.list_keys()
        if keys is None:
            print("   [warn] Не удалось получить список объектов S3, S3-сверка пропущена")
            return
        key_set = set(keys)

        media_list = await self._load_all_media()
        for m in media_list:
            if m.s3_key:
                if m.s3_key in key_set:
                    if m.download_status != "verified":
                        m.download_status = "verified"
                        print(f"   [ok] S3 подтверждён (media #{m.id}): {m.original_name}")
                else:
                    # Объект пропал из S3 — перезаливаем или помечаем missing
                    local_file = self.storage.get_file_path(m.local_path) if m.local_path else None
                    if local_file and local_file.exists():
                        print(f"   🔄 Перезаливаю в S3 (media #{m.id}): {m.original_name}")
                        file_id = await self.s3.upload_file(
                            local_file,
                            m.s3_key,
                            content_type=m.mime_type,
                        )
                        m.download_status = "uploaded" if file_id else "missing"
                    else:
                        m.download_status = "missing"
                        print(f"   [err] Объект S3 не найден и локальной копии нет (media #{m.id}): {m.original_name}")
            else:
                # Нет s3_key — выгружаем, если есть локальный файл
                if m.download_status in ("new", "downloaded") and m.local_path:
                    local_file = self.storage.get_file_path(m.local_path)
                    if local_file.exists():
                        remote_key = f"board_{m.board_id}/thread_{m.thread_id}/{Path(m.local_path).name}"
                        file_id = await self.s3.upload_file(
                            local_file,
                            remote_key,
                            content_type=m.mime_type,
                        )
                        if file_id:
                            m.s3_key = remote_key
                            m.download_status = "uploaded"
                            print(f"   📤 Выгружен в S3 (media #{m.id}): {m.original_name}")