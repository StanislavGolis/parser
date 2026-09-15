# src/services/pipeline.py
"""Конвейер файла: подготовка → S3 и деривативы → строка в БД.

Логика не знает, с какого сайта файл: она работает с метаданными, которые
готовит адаптер источника (`src/parsers/`), поэтому новый источник получает
скачивание, валидацию, выгрузку в S3, деривативы и запись в БД «бесплатно».
Об источнике конвейер знает только заголовки скачивания (`download_headers`):
часть сайтов не отдаёт файлы без `Referer` (403).

Стадии разделены, чтобы тяжёлая часть (S3 + деривативы) шла параллельно
подготовке следующих файлов, а запись в БД оставалась последовательной
(сессия одна, конкурентные flush недопустимы).
"""
import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.models import BlockedHash, Board, Media, ThreadState
from src.repositories.media_repo import MediaRepository, UPLOADED_STATUSES
from src.services.s3_storage import S3Storage
from src.services.downloader import DownloaderService
from src.services.derivatives import generate_and_upload
from src.services.media_cache import CachingUploader, get_media_cache
from src.services.media_validator import MediaValidator
from src.services.storage import StorageService


@dataclass
class PreparedFile:
    """Файл, прошедший фильтр/дедупликацию/валидацию и сохранённый локально.

    Разделение обработки на стадии нужно, чтобы тяжёлая часть (загрузка в S3 и
    построение деривативов) шла параллельно для нескольких файлов, пока для
    следующих файлов выполняется подготовка. Запись в БД остаётся
    последовательной: сессия одна, конкурентные `flush` недопустимы.
    """
    meta: dict
    file_data: bytes
    file_sha256: str
    storage_path: str
    local_path: Path
    same_thread: Optional[Media] = None


class FilePipeline:
    """Стадии обработки файлов источника (см. docstring модуля)."""

    def __init__(
        self,
        session: AsyncSession,
        download_headers: Optional[Dict[str, str]] = None,
    ):
        self.session = session
        self.media_repo = MediaRepository(session)
        self.downloader = DownloaderService()
        self.storage = StorageService(settings.STORAGE_PATH)
        self.s3_storage = S3Storage()
        # Заголовки запросов к источнику (Referer/UA): часть сайтов без них
        # отдаёт 403 на видео — адаптер передаёт свои.
        self.download_headers = dict(download_headers or {})


    async def prefetch_batch(
        self,
        files: List[dict],
        board: Board,
        thread_state: ThreadState,
    ) -> Dict[str, bytes]:
        """Параллельно скачивает файлы пачки (дедупликация — до загрузки).

        Проверки «уже сохранён в треде» / «дубль по md5» и фильтр по метаданным
        выполняются здесь **до** скачивания — ровно те же, что в `_prepare_file`,
        поэтому в сеть уходят только файлы, которых у нас ещё нет, и повторных
        вставок не будет. Ограничения: `MAX_PARALLEL_DOWNLOADS` (сколько запросов
        одновременно) и `PREFETCH_MAX_BYTES` (суммарный объём пачки; крупные файлы
        пропускаются и качаются по одному в `_prepare_file`).

        Возвращает {source_md5: байты} — только успешно скачанное.
        """
        todo: List[dict] = []
        seen = set()
        budget = int(settings.PREFETCH_MAX_BYTES)
        for meta in files:
            md5 = meta.get("md5")
            if not md5 or md5 in seen:
                continue
            valid, _ = MediaValidator.is_allowed(
                meta["filename"],
                meta["size_bytes"],
                meta["media_type"],
                meta.get("width"),
                meta.get("height"),
            )
            if not valid:
                continue
            same_thread = await self.media_repo.get_by_board_thread_md5(
                board.id, thread_state.thread_id, md5
            )
            if (
                same_thread
                and same_thread.s3_key
                and same_thread.download_status in UPLOADED_STATUSES
            ):
                continue
            if same_thread is None and await self.media_repo.get_by_md5(md5) is not None:
                continue

            size = int(meta.get("size_bytes") or 0)
            if size > budget:
                continue  # крупный файл — скачаем по одному, не держим в памяти
            budget -= size
            seen.add(md5)
            todo.append(meta)

        if not todo:
            return {}

        semaphore = asyncio.Semaphore(max(1, int(settings.MAX_PARALLEL_DOWNLOADS)))

        async def download_one(meta: dict):
            async with semaphore:
                # Пауза держится внутри семафора: суммарный темп запросов к форуму
                # не выше, чем в последовательном режиме (REQUEST_DELAY на запрос)
                await asyncio.sleep(settings.REQUEST_DELAY)
                data = await self.downloader.download(meta["file_url"], headers=self.download_headers or None)
                if data:
                    print(
                        f"   [par]  Скачано параллельно: {meta['original_name']} "
                        f"({len(data)} байт)"
                    )
                return meta["md5"], data

        results = await asyncio.gather(
            *(download_one(meta) for meta in todo), return_exceptions=True
        )
        fetched: Dict[str, bytes] = {}
        for result in results:
            if isinstance(result, BaseException):
                print(f"   [warn] Параллельная загрузка не удалась: {result}")
                continue
            md5, data = result
            if data:
                fetched[md5] = data
        return fetched


    async def prepare_file(
        self,
        board: Board,
        thread_state: ThreadState,
        meta: dict,
        file_data: Optional[bytes] = None,
    ) -> "PreparedFile | str":
        """Стадия 1: фильтр → дедупликация → скачивание → валидация → локальный файл.

        `file_data` — байты, уже скачанные параллельно (`_prefetch_batch`): фильтр
        и дедупликация всё равно выполняются здесь, поэтому повторных вставок не
        будет; если байтов нет — файл скачивается самостоятельно.

        Возвращает `PreparedFile` (файл готов к выгрузке в S3 и записи в БД) либо
        строковый статус, когда файл обрабатывать не нужно: `have` (уже был в этом
        треде), `dup` (ссылка-дубль), `invalid` (битый на форуме), `filtered`
        (не прошёл правила размера/разрешения), `err` (наша ошибка).
        """
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
                return "filtered"

            # 2. Дедупликация по source_md5 (до скачивания)
            # 2.1. Файл уже есть в ЭТОМ треде — повторный проход не должен
            #      создавать новую запись (иначе статистика и галерея удваиваются).
            same_thread = await self.media_repo.get_by_board_thread_md5(
                board.id, thread_state.thread_id, meta["md5"]
            )
            if (
                same_thread
                and same_thread.s3_key
                and same_thread.download_status in UPLOADED_STATUSES
            ):
                print(f"   [have] Файл уже сохранён в треде: {meta['original_name']}")
                return "have"

            # 2.2. Такой же файл есть в другом треде/доске — пишем ссылку-дубль
            #      (объект в S3 переиспользуем, повторно не скачиваем).
            existing = await self.media_repo.get_by_md5(meta["md5"])
            if existing and same_thread is None:
                dup = await self.media_repo.create(
                    board_id=board.id,
                    thread_id=thread_state.thread_id,
                    source_id=board.source_id,   # источник = источник доски
                    original_name=meta["original_name"],
                    source_url=meta["file_url"],
                    source_md5=meta["md5"],
                    file_size=meta["size_bytes"],
                    mime_type=meta["mime_type"],
                    media_type=meta["media_type"],
                    width=meta.get("width"),
                    height=meta.get("height"),
                    duplicate_of_id=existing.id,
                    s3_key=existing.s3_key,
                    s3_bucket=existing.s3_bucket,
                    download_status=(
                        "uploaded" if existing.download_status in ("uploaded", "verified") else "new"
                    ),
                    is_visible=existing.is_visible,
                    is_active=True,
                    is_premium=bool(board.is_premium or thread_state.is_premium),
                )
                await self.session.flush()
                print(f"   [dup] Дубль по md5 {meta['md5'][:8]}: duplicate ID {dup.id} → {existing.id}")
                return "dup"

            # 3. Скачивание (если байты не переданы заранее параллельным режимом)
            if file_data is None:
                print(f"   [down] Скачиваем: {meta['original_name']}")
                file_data = await self.downloader.download(meta["file_url"], headers=self.download_headers or None)
                if not file_data:
                    return "err"

            # 4. Целостность: md5 из API должен совпасть с фактическим
            #    (CDN может пережимать картинки, поэтому для image не фатально).
            #    У источников без md5 (сайты) он синтетический (`md5(url)`) —
            #    сверять нечего: точная проверка идёт по SHA-256 ниже
            file_md5 = MediaValidator.compute_md5(file_data)
            integrity_ok = file_md5 == meta["md5"]
            if not integrity_ok and not meta.get("md5_synthetic") and meta["media_type"] == "video":
                print(f"   [del]  Битый файл (md5 не совпал): {meta['original_name']}")
                return "invalid"

            if meta["media_type"] == "image":
                ok_img, img_err = MediaValidator.verify_image(file_data)
                if not ok_img:
                    print(f"   [del]  Битое изображение: {meta['original_name']} — {img_err}")
                    return "invalid"
                if not integrity_ok:
                    print(f"   [warn] md5 из API не совпал (вероятно CDN-пережим), но изображение валидно: {meta['original_name']}")

            file_sha256 = MediaValidator.compute_sha256(file_data)

            # 4.1. Тот же контент уже сохранён (SHA-256), но source_md5 другой:
            # 2ch/CDN отдают разные md5 для одной и той же картинки. Раньше здесь
            # INSERT падал на UNIQUE(media.file_hash), транзакция треда «травилась»
            # и тред не мог дойти до конца (повторные прогоны не добавляли файлы).
            twin = await self.media_repo.get_by_hash(file_sha256)
            if twin is not None and (same_thread is None or twin.id != same_thread.id):
                if same_thread is None:
                    dup = await self.media_repo.create(
                        board_id=board.id,
                        thread_id=thread_state.thread_id,
                        source_id=board.source_id,
                        original_name=meta["original_name"],
                        source_url=meta["file_url"],
                        source_md5=meta["md5"],
                        file_size=meta["size_bytes"],
                        mime_type=meta["mime_type"],
                        media_type=meta["media_type"],
                        variants=twin.variants,
                        duration_seconds=twin.duration_seconds,
                        width=meta.get("width"),
                        height=meta.get("height"),
                        duplicate_of_id=twin.id,
                        s3_key=twin.s3_key,
                        s3_bucket=twin.s3_bucket,
                        download_status=twin.download_status,
                        is_visible=twin.is_visible,
                        is_active=True,
                        is_premium=bool(board.is_premium or thread_state.is_premium),
                    )
                    await self.session.flush()
                    print(
                        f"   [dup] Дубль по sha256 {file_sha256[:8]}: "
                        f"ID {dup.id} → {twin.id}"
                    )
                else:
                    # Строка в этом треде есть, но без объекта — берём объект у двойника
                    same_thread.duplicate_of_id = twin.id
                    same_thread.s3_key = twin.s3_key
                    same_thread.s3_bucket = twin.s3_bucket
                    same_thread.variants = twin.variants
                    same_thread.duration_seconds = twin.duration_seconds
                    same_thread.download_status = twin.download_status
                    same_thread.is_active = True
                    same_thread.is_premium = bool(board.is_premium or thread_state.is_premium)
                    await self.session.flush()
                    print(
                        f"   [dup] Дубль по sha256 {file_sha256[:8]}: "
                        f"ID {same_thread.id} → {twin.id}"
                    )
                return "dup"

            # 5. Сохранение в локальное хранилище (кэш)
            storage_path = await self.storage.save(
                file_data,
                board_id=board.id,
                thread_id=thread_state.thread_id,
                filename=meta["filename"],
            )
            return PreparedFile(
                meta=meta,
                file_data=file_data,
                file_sha256=file_sha256,
                storage_path=storage_path,
                local_path=self.storage.get_file_path(storage_path),
                same_thread=same_thread,
            )

        except Exception as e:
            print(f"   [err] Ошибка при обработке {meta.get('original_name', '?')}: {e}")
            return "err"


    async def upload_file(
        self, board: Board, thread_state: ThreadState, prepared: PreparedFile
    ) -> Dict[str, object]:
        """Стадия 2 (без БД): оригинал в S3 + деривативы (превью/оптимизация).

        Держит только сетевую и CPU-работу, поэтому может идти параллельно для
        нескольких файлов, пока для следующих файлов выполняется подготовка.
        """
        meta = prepared.meta
        s3_key = None
        variants = None
        duration_seconds = None
        remote_key = f"board_{board.id}/thread_{thread_state.thread_id}/{meta['filename']}"
        if self.s3_storage.is_configured:
            s3_key = await self.s3_storage.upload_file(
                prepared.local_path,
                remote_key,
                content_type=meta["mime_type"],
            )

        if s3_key:
            variants, duration_seconds = await self.build_variants(
                board,
                thread_state,
                meta,
                prepared.file_data,
                prepared.file_sha256,
                prepared.local_path,
            )
            if prepared.local_path.exists():
                # Раньше скачанный оригинал просто удалялся. Теперь оставляем его
                # в локальном кэше: сайт отдаёт файл с диска (500+ МБ/с против
                # ~3 МБ/с у S3) без повторного скачивания — «бесплатный» прогрев.
                cache = get_media_cache()
                cached = await asyncio.to_thread(
                    cache.store_path, remote_key, prepared.local_path, True
                )
                if cached is None:
                    os.remove(prepared.local_path)
                    print(f"   [del]  Локальный файл удалён: {meta['filename']}")
                else:
                    print(f"   [cache] Оригинал оставлен в кэше: {meta['filename']}")

        return {
            "s3_key": s3_key,
            "variants": variants,
            "duration_seconds": duration_seconds,
        }


    async def run_upload(
        self, board: Board, thread_state: ThreadState, prepared: PreparedFile
    ) -> Dict[str, object]:
        """Обёртка стадии 2 для параллельного окна: ошибка не роняет тред."""
        try:
            return await self.upload_file(board, thread_state, prepared)
        except Exception as e:  # noqa: BLE001
            print(
                f"   [err] Ошибка выгрузки {prepared.meta.get('original_name', '?')}: {e}"
            )
            return {}


    async def _is_blocked(self, file_sha256: Optional[str]) -> bool:
        """Есть ли хеш файла в блок-листе запрещённого контента.

        Список ведётся в админке (вкладка жалоб) и пополняется автоскрытием по
        жалобе с причиной `csam`, поэтому проверка закрывает повторные попытки
        скачать тот же файл заново или притащить его из архива.
        """
        if not file_sha256:
            return False
        row = await self.session.execute(
            select(BlockedHash.id).where(BlockedHash.sha256 == file_sha256).limit(1)
        )
        return row.scalar_one_or_none() is not None

    async def write_media(
        self,
        board: Board,
        thread_state: ThreadState,
        prepared: PreparedFile,
        payload: Dict[str, object],
    ) -> str:
        """Стадия 3 (в БД, последовательно): строка `media` в SAVEPOINT.

        Запись идёт в savepoint, поэтому ошибка одного файла (например, конфликт
        `UNIQUE(media.file_hash)`) не «травит» транзакцию всего треда.
        """
        meta = prepared.meta
        same_thread = prepared.same_thread
        storage_path = prepared.storage_path
        file_sha256 = prepared.file_sha256
        s3_key = payload.get("s3_key")
        variants = payload.get("variants")
        duration_seconds = payload.get("duration_seconds")
        # Блок-лист запрещённого контента: такой файл сохраняем скрытым — он остаётся
        # в архиве для истории модерации, но на сайте и в лентах не появляется
        # (см. `/admin/reports` → блок-лист хешей).
        blocked = await self._is_blocked(file_sha256)
        try:
            # Новую строку создаём только для новых файлов, а запись без объекта в
            # S3 (например, прошлый раз не докачали) обновляем — так повторные
            # проходы не размножают строки.
            async with self.session.begin_nested():
                if same_thread is not None:
                    media = same_thread
                    media.original_name = meta["original_name"]
                    media.source_url = meta["file_url"]
                    media.source_id = board.source_id   # источник = источник доски
                    media.local_path = storage_path
                    media.file_hash = file_sha256
                    media.file_size = meta["size_bytes"]
                    media.mime_type = meta["mime_type"]
                    media.media_type = meta["media_type"]
                    media.width = meta.get("width")
                    media.height = meta.get("height")
                    if meta.get("post_num"):
                        media.source_order = int(meta["post_num"])
                    if s3_key:
                        media.s3_bucket = settings.storage_bucket
                        media.s3_key = s3_key
                    if variants:
                        media.variants = variants
                    if duration_seconds:
                        media.duration_seconds = duration_seconds
                    media.download_status = "uploaded" if s3_key else "downloaded"
                    media.is_active = True
                    if blocked:
                        media.is_visible = False
                    media.is_premium = bool(board.is_premium or thread_state.is_premium)
                    await self.session.flush()
                else:
                    media = await self.media_repo.create(
                        board_id=board.id,
                        thread_id=thread_state.thread_id,
                        source_id=board.source_id,   # источник = источник доски
                        original_name=meta["original_name"],
                        source_url=meta["file_url"],
                        local_path=storage_path,
                        file_hash=file_sha256,
                        source_md5=meta["md5"],
                        file_size=meta["size_bytes"],
                        mime_type=meta["mime_type"],
                        media_type=meta["media_type"],
                        s3_bucket=settings.storage_bucket if s3_key else None,
                        s3_key=s3_key,
                        variants=variants,
                        duration_seconds=duration_seconds,
                        width=meta.get("width"),
                        height=meta.get("height"),
                        # Порядок файла в треде у источника: по нему тред читается
                        # «с начала», а новые файлы встают в конец (см. board_media)
                        source_order=int(meta.get("post_num") or 0) or None,
                        download_status="uploaded" if s3_key else "downloaded",
                        is_visible=not blocked,
                        is_active=True,
                        is_premium=bool(board.is_premium or thread_state.is_premium),
                    )
                    await self.session.flush()
        except Exception as e:  # noqa: BLE001
            print(f"   [err] Ошибка записи {meta.get('original_name', '?')}: {e}")
            return "err"

        if self.s3_storage.is_configured and not s3_key:
            # Не выгрузилось в S3: строка осталась «локальной», повторим в следующий
            # проход (условие `[have]` требует объект в S3, файл будет дозакачан)
            print(f"   [warn] Не выгружено в S3: {meta['original_name']} (ID: {media.id})")
            return "err"
        if s3_key:
            print(f"   [ok] Загружен в S3: {meta['original_name']} (ID: {media.id})")
        else:
            print(f"   [warn] Сохранён локально: {meta['original_name']} (ID: {media.id}, статус: downloaded)")
        return "saved"


    async def process_file(
        self,
        board: Board,
        thread_state: ThreadState,
        meta: dict,
        file_data: Optional[bytes] = None,
    ) -> str:
        """Последовательная обработка файла: подготовка → S3 → запись в БД.

        Используется, когда параллельное окно выключено (`MAX_PARALLEL_UPLOADS=1`).
        При большем значении `scan_thread` запускает стадии 2–3 конвейером, чтобы
        тяжёлая часть (S3 + деривативы) шла параллельно подготовке следующих файлов.
        """
        prepared = await self.prepare_file(board, thread_state, meta, file_data)
        if isinstance(prepared, str):
            return prepared
        payload = await self.run_upload(board, thread_state, prepared)
        return await self.write_media(board, thread_state, prepared, payload)


    async def build_variants(
        self,
        board: Board,
        thread_state: ThreadState,
        meta: dict,
        file_data: bytes,
        file_sha256: str,
        local_path: Path,
    ):
        """Строит и загружает деривативы: thumb/web (WebP) или poster/720p (видео).

        Возвращает (variants: dict|None, duration_seconds: float|None).
        """
        prefix = file_sha256[:12]
        base = f"board_{board.id}/thread_{thread_state.thread_id}/{prefix}"
        try:
            # Обёртка кладёт готовые деривативы в локальный кэш: они уже в памяти
            # или на диске, поэтому сайт отдаёт их без обращения к S3.
            variants, duration = await generate_and_upload(
                CachingUploader(self.s3_storage, get_media_cache()),
                base_key=base,
                media_type=meta["media_type"],
                local_path=local_path,
                file_data=file_data,
                # Архивный источник отключает транскод видео (см. VIDEO_WEB_ENABLED)
                video_web=settings.VIDEO_WEB_ENABLED,
            )
        except Exception as e:  # noqa: BLE001
            print(f"   [warn] деривативы не построены ({meta.get('original_name', '?')}): {e}")
            return None, None
        if variants:
            print(f"   [img]  Деривативы: {', '.join(variants.keys())}")
        return variants, duration

