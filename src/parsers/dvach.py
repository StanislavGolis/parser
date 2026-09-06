# src/parsers/dvach.py
"""Парсер 2ch.hk на JSON API.

- catalog.json           -> список тредов доски (posts_count / files_count для инкрементности);
- thread/{num}.json      -> посты и метаданные файлов (md5, size, width, height) ДО скачивания;
- дедупликация по source_md5 выполняется до скачивания;
- состояние тредов в threads_state — при неизменных счётчиках тред пропускается.
"""
import asyncio
import os
from datetime import datetime
from typing import List, Optional

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.models import Board, Media, ThreadState
from src.repositories.board_repo import BoardRepository
from src.repositories.media_repo import MediaRepository
from src.repositories.thread_state_repo import ThreadStateRepository
from src.services.b2_uploader import B2Uploader
from src.services.downloader import DownloaderService
from src.services.media_validator import MediaValidator
from src.services.reconciliation import ReconciliationService
from src.services.storage import StorageService

MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mkv": "video/x-matroska",
}


class DvachParser:
    """Инкрементальный парсер досок 2ch.hk."""

    BASE_URL = "https://2ch.hk"

    def __init__(self, session: AsyncSession):
        self.session = session
        self.board_repo = BoardRepository(session)
        self.thread_state_repo = ThreadStateRepository(session)
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

    # ───────────────────────── HTTP / JSON ─────────────────────────

    async def _get_json(self, url: str) -> Optional[dict]:
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            async with self.http_session.get(url, timeout=timeout, headers=headers) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as e:
            print(f"   [err] HTTP {url}: {e}")
            return None

    @staticmethod
    def _extract_posts(data: dict) -> List[dict]:
        """thread.json приходит как {"threads": [{"posts": [...]}]} или {"posts": [...]}."""
        if isinstance(data.get("threads"), list):
            posts: List[dict] = []
            for thread in data["threads"]:
                posts.extend(thread.get("posts") or [])
            return posts
        if isinstance(data.get("posts"), list):
            return data["posts"]
        return []

    # ───────────────────── Метаданные файлов ─────────────────────

    def _file_meta(self, file: dict) -> Optional[dict]:
        """Нормализует файл из API. Возвращает None, если файл не подходит.

        В API двача размер файла указан в КБ.
        """
        filename = file.get("name") or ""
        media_type = MediaValidator.classify(filename)
        if not media_type:
            return None

        path = file.get("path") or ""
        if not path:
            return None

        md5 = (file.get("md5") or "").strip().lower()
        if not md5:
            return None

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        size_bytes = int(file.get("size") or 0) * 1024

        return {
            "filename": filename,
            "original_name": file.get("displayname") or filename,
            "md5": md5,
            "file_url": f"{self.BASE_URL}{path}",
            "size_bytes": size_bytes,
            "mime_type": MIME_BY_EXT.get(ext, "application/octet-stream"),
            "media_type": media_type,
            "width": file.get("width"),
            "height": file.get("height"),
        }

    async def fetch_thread_files(self, board_slug: str, thread_id: int) -> List[dict]:
        """Возвращает метаданные файлов треда (без скачивания файлов)."""
        url = f"{self.BASE_URL}/{board_slug}/res/{thread_id}.json"
        data = await self._get_json(url)
        if not data:
            return []

        files: List[dict] = []
        for post in self._extract_posts(data):
            for f in post.get("files") or []:
                meta = self._file_meta(f)
                if meta:
                    files.append(meta)
        return files

    # ───────────────────── Обработка доски ─────────────────────

    async def process_board(self, board_slug: str):
        """Полный цикл обработки одной доски."""
        print(f"[info] Начинаем парсинг доски /{board_slug}")
        catalog = await self._get_json(f"{self.BASE_URL}/{board_slug}/catalog.json")
        if not catalog:
            print(f"   [err] Не удалось получить каталог /{board_slug}")
            return

        board_info = catalog.get("board", {})

        # Доска в БД
        board, _ = await self.board_repo.get_or_create(
            slug=board_slug,
            defaults={
                "title": board_info.get("name") or board_slug.upper(),
                "is_visible": True,
            },
        )
        if board_info.get("name"):
            board.title = board_info["name"]
        if board_info.get("info_outer") and not board.description:
            board.description = board_info["info_outer"]
        await self.session.flush()

        catalog_threads = [t for t in catalog.get("threads", []) if t.get("num")]
        current_ids = {int(t["num"]) for t in catalog_threads}
        print(f"   В каталоге /{board_slug}: {len(catalog_threads)} тредов")

        scanned = 0
        for t in catalog_threads:
            thread_id = int(t["num"])
            posts_count = int(t.get("posts_count") or 0)
            files_count = int(t.get("files_count") or 0)

            state = await self.thread_state_repo.get_by_board_thread(board.id, thread_id)
            if state is None:
                state = ThreadState(
                    board_id=board.id,
                    thread_id=thread_id,
                    posts_count=posts_count,
                    files_count=files_count,
                    is_active=True,
                )
                self.session.add(state)
                need_scan = True
                reason = "новый тред"
            else:
                state.is_active = True
                need_scan = (state.posts_count != posts_count) or (state.files_count != files_count)
                reason = "изменения" if need_scan else \
                    f"без изменений (постов: {state.posts_count}, файлов: {state.files_count})"

            if need_scan:
                files = await self.fetch_thread_files(board_slug, thread_id)
                print(f"   [thread] Тред {thread_id} — {reason}: {len(files)} файлов")
                for meta in files:
                    await self.process_file(board, state, meta)
                    await asyncio.sleep(settings.REQUEST_DELAY * 0.5)

                state.posts_count = posts_count
                state.files_count = files_count
                state.last_scanned_at = datetime.utcnow()
                scanned += 1
            else:
                print(f"   [skip]  Тред {thread_id} — {reason}")

            await asyncio.sleep(settings.REQUEST_DELAY)

        # Треды, исчезнувшие из каталога
        active_states = await self.thread_state_repo.get_active_by_board(board.id)
        deactivated = 0
        for st in active_states:
            if st.thread_id not in current_ids:
                st.is_active = False
                deactivated += 1
        if deactivated:
            print(f"   [off] Деактивировано тредов: {deactivated}")

        await self.session.commit()
        print(f"[ok] Парсинг доски /{board_slug} завершён (просканировано тредов: {scanned})")

    # ───────────────────── Обработка файла ─────────────────────

    async def process_file(self, board: Board, thread_state: ThreadState, meta: dict):
        """Скачивание, валидация, загрузка в B2 и запись в БД одного файла."""
        try:
            # 1. Фильтрация по метаданным (до скачивания)
            valid, error = MediaValidator.is_allowed(
                meta["filename"],
                meta["size_bytes"],
                meta["media_type"],
                meta.get("width"),
                meta.get("height"),
            )
            if not valid:
                print(f"   [skip] Отфильтрован: {meta['original_name']} — {error}")
                return

            # 2. Дедупликация по source_md5 (до скачивания)
            existing = await self.media_repo.get_by_md5(meta["md5"])
            if existing:
                dup = await self.media_repo.create(
                    board_id=board.id,
                    thread_id=thread_state.thread_id,
                    original_name=meta["original_name"],
                    source_url=meta["file_url"],
                    source_md5=meta["md5"],
                    file_size=meta["size_bytes"],
                    mime_type=meta["mime_type"],
                    media_type=meta["media_type"],
                    width=meta.get("width"),
                    height=meta.get("height"),
                    duplicate_of_id=existing.id,
                    b2_key=existing.b2_key,
                    b2_bucket=existing.b2_bucket,
                    download_status=(
                        "uploaded" if existing.download_status in ("uploaded", "verified") else "new"
                    ),
                    is_visible=existing.is_visible,
                    is_active=True,
                )
                await self.session.flush()
                print(f"   [dup] Дубль по md5 {meta['md5'][:8]}: duplicate ID {dup.id} → {existing.id}")
                return

            # 3. Скачивание
            print(f"   [down] Скачиваем: {meta['original_name']}")
            file_data = await self.downloader.download(meta["file_url"])
            if not file_data:
                return

            # 4. Целостность: md5 из API должен совпасть с фактическим
            #    (CDN может пережимать картинки, поэтому для image не фатально)
            file_md5 = MediaValidator.compute_md5(file_data)
            integrity_ok = file_md5 == meta["md5"]
            if not integrity_ok and meta["media_type"] == "video":
                print(f"   [del]  Битый файл (md5 не совпал): {meta['original_name']}")
                return

            if meta["media_type"] == "image":
                ok_img, img_err = MediaValidator.verify_image(file_data)
                if not ok_img:
                    print(f"   [del]  Битое изображение: {meta['original_name']} — {img_err}")
                    return
                if not integrity_ok:
                    print(f"   [warn] md5 из API не совпал (вероятно CDN-пережим), но изображение валидно: {meta['original_name']}")

            file_sha256 = MediaValidator.compute_sha256(file_data)

            # 5. Сохранение в локальное хранилище (кэш)
            storage_path = await self.storage.save(
                file_data,
                board_id=board.id,
                thread_id=thread_state.thread_id,
                filename=meta["filename"],
            )

            # 6. Загрузка в B2 (если настроен)
            b2_key = None
            local_deleted = False
            if self.b2_uploader.is_configured:
                remote_key = f"board_{board.id}/thread_{thread_state.thread_id}/{meta['filename']}"
                b2_key = await self.b2_uploader.upload_file(
                    self.storage.get_file_path(storage_path),
                    remote_key,
                )
                if b2_key:
                    local_path = self.storage.get_file_path(storage_path)
                    if local_path.exists():
                        os.remove(local_path)
                        local_deleted = True
                        print(f"   [del]  Локальный файл удалён: {meta['filename']}")

            # 7. Запись в БД
            media = await self.media_repo.create(
                board_id=board.id,
                thread_id=thread_state.thread_id,
                original_name=meta["original_name"],
                source_url=meta["file_url"],
                local_path=storage_path,
                file_hash=file_sha256,
                source_md5=meta["md5"],
                file_size=meta["size_bytes"],
                mime_type=meta["mime_type"],
                media_type=meta["media_type"],
                b2_bucket=settings.B2_BUCKET_NAME if b2_key else None,
                b2_key=b2_key,
                width=meta.get("width"),
                height=meta.get("height"),
                download_status="uploaded" if b2_key else "downloaded",
                is_visible=True,
                is_active=True,
            )
            await self.session.flush()

            if b2_key:
                print(f"   [ok] Загружен в B2: {meta['original_name']} (ID: {media.id})")
            else:
                print(f"   [warn] Сохранён локально: {meta['original_name']} (ID: {media.id}, статус: downloaded)")

        except Exception as e:
            print(f"   [err] Ошибка при обработке {meta.get('original_name', '?')}: {e}")

    # ───────────────────── Reconciliation ─────────────────────

    async def run_reconciliation(self) -> None:
        """Сверка БД с локальным кэшем и B2 (актуальность данных и хранилища)."""
        print("[sync] Запуск сверки данных (reconciliation)...")
        service = ReconciliationService(self.session, self.storage, self.b2_uploader)
        await service.run()