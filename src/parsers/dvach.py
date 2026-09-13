# src/parsers/dvach.py
"""Парсер 2ch.hk на JSON API.

- catalog.json           -> список тредов доски (posts_count / files_count для инкрементности);
- thread/{num}.json      -> посты и метаданные файлов (md5, size, width, height) ДО скачивания;
- дедупликация по source_md5 выполняется до скачивания;
- состояние тредов в threads_state — при неизменных счётчиках тред пропускается.
"""
import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiohttp
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.models import Board, Media, ThreadState
from src.core.redis_client import redis_client
from src.repositories.board_repo import BoardRepository
from src.repositories.media_repo import MediaRepository
from src.repositories.thread_state_repo import FRESH_REASONS, ThreadStateRepository
from src.services.catalog_health import mark_catalog_error, mark_catalog_ok
from src.services.s3_storage import S3Storage
from src.services.downloader import DownloaderService
from src.services.derivatives import generate_and_upload
from src.services.media_cache import CachingUploader, get_media_cache
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

# Статусы, при которых файл лежит в объектном хранилище
UPLOADED_STATUSES = ("uploaded", "verified")


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


class DvachParser:
    """Инкрементальный парсер досок 2ch.hk."""

    BASE_URL = "https://2ch.hk"

    def __init__(self, session: AsyncSession):
        self.session = session
        self.board_repo = BoardRepository(session)
        self.thread_state_repo = ThreadStateRepository(session)
        self.media_repo = MediaRepository(session)
        # Callback «остановить доску» (проверяется между тредами). Задаёт main.py.
        self.stop_check = None

        self.downloader = DownloaderService()
        self.storage = StorageService(settings.STORAGE_PATH)
        self.s3_storage = S3Storage()

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

    async def fetch_thread_files(self, board_slug: str, thread_id: int) -> Optional[List[dict]]:
        """Возвращает метаданные файлов треда (без скачивания файлов).

        `None` — не удалось прочитать `res/{id}.json` (сеть/ошибка): вызывающий
        оставляет тред в очереди, а не считает его просканированным. Пустой
        список — в треде действительно нет «наших» файлов.
        """
        url = f"{self.BASE_URL}/{board_slug}/res/{thread_id}.json"
        data = await self._get_json(url)
        if data is None:
            return None

        files: List[dict] = []
        for post in self._extract_posts(data):
            post_num = int(post.get("num") or 0)
            for f in post.get("files") or []:
                meta = self._file_meta(f)
                if meta:
                    # Номер поста нужен для инкрементального прохода:
                    # частые сканы смотрят только посты новее `last_post_num`.
                    meta["post_num"] = post_num
                    files.append(meta)
        return files

    # ───────────────────── Обработка доски ─────────────────────

    async def ensure_configured_boards(self) -> None:
        """Создаёт в БД доски из BOARDS_TO_PARSE, которых ещё нет (первый запуск).

        Новые доски создаются выключенными (parse_enabled=False, is_visible=False):
        их включает админ. Уже существующие доски не трогаем.
        """
        print("[init] Проверка/создание досок из конфигурации...")
        cnt = (await self.session.execute(select(func.count()).select_from(Board))).scalar() or 0
        if cnt > 0:
            print("[init] Доски уже настроены в БД — автозаполнение из конфигурации пропущено")
            return

        for board_slug in settings.BOARDS_TO_PARSE:
            catalog = await self._get_json(f"{self.BASE_URL}/{board_slug}/catalog.json")
            if not catalog:
                print(f"   [warn] Доска /{board_slug} не ответила каталогом — пропускаю")
                continue

            board_info = catalog.get("board", {})
            board, created = await self.board_repo.get_or_create(
                slug=board_slug,
                defaults={
                    "title": board_info.get("name") or board_slug.upper(),
                    "description": board_info.get("info_outer"),
                    "is_visible": False,
                    "parse_enabled": False,
                },
            )
            # Название с форума берём только если его ещё не задали вручную в админке
            if board_info.get("name") and (not board.title or board.title.lower() == board.slug):
                board.title = board_info["name"]
            if board_info.get("info_outer") and not board.description:
                board.description = board_info["info_outer"]
            await self.session.flush()
            print(f"   [ok] Доска /{board_slug} — {'создана' if created else 'уже в БД'}")

        await self.session.commit()

    @staticmethod
    def _clean_comment(html: Optional[str]) -> Optional[str]:
        """Переводит HTML-комментарий ОП в короткий plaintext для хранения."""
        if not html:
            return None
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:400] or None

    @staticmethod
    def _thread_meta(t: dict) -> dict:
        """Вытаскивает отображаемые метаданные треда из элемента каталога."""
        ts = t.get("timestamp")
        return {
            "subject": (t.get("subject") or "").strip()[:500] or None,
            "comment": DvachParser._clean_comment(t.get("comment")),
            "thread_timestamp": datetime.fromtimestamp(int(ts)) if ts else None,
        }

    PROGRESS_KEY = "parser:progress"

    async def _progress(self, **fields) -> None:
        """Публикует прогресс парсера в Redis (для админки, TTL 5 мин)."""
        payload = {"updated_at": datetime.utcnow().isoformat(), **fields}
        try:
            await redis_client.set(self.PROGRESS_KEY, json.dumps(payload), ex=300)
        except Exception:
            pass

    async def _clear_progress(self) -> None:
        try:
            await redis_client.delete(self.PROGRESS_KEY)
        except Exception:
            pass

    async def sync_board_catalog(self, board_slug: str) -> Optional[int]:
        """Фаза A: каталог доски → метаданные тредов и очередь на докачку.

        Скачивается только `catalog.json` (1 запрос на доску), файлы — нет,
        поэтому все доски обходятся за минуты. Возвращает число тредов в
        каталоге (None — каталог недоступен).
        """
        print(f"[info] Каталог доски /{board_slug}")
        await self._progress(board_slug=board_slug, phase="catalog")
        catalog = await self._get_json(f"{self.BASE_URL}/{board_slug}/catalog.json")
        if not catalog:
            # Раздел мог быть удалён с форума (2ch отдаёт 500 «Not found»), а
            # index.json всё ещё его перечисляет — фиксируем в Redis, чтобы
            # админка показала «каталог недоступен» на карточке доски.
            await mark_catalog_error(
                board_slug, "2ch не отдал каталог (500/404 или сеть) — раздел удалён?"
            )
            print(f"   [err] Не удалось получить каталог /{board_slug}")
            await self._clear_progress()
            return None
        await mark_catalog_ok(board_slug)

        board_info = catalog.get("board", {})

        # Доска в БД
        board, _ = await self.board_repo.get_or_create(
            slug=board_slug,
            defaults={
                "title": board_info.get("name") or board_slug.upper(),
                "is_visible": False,
            },
        )
        # Название с форума берём только если его ещё не задали вручную в админке
        if board_info.get("name") and (not board.title or board.title.lower() == board.slug):
            board.title = board_info["name"]
        if board_info.get("info_outer") and not board.description:
            board.description = board_info["info_outer"]
        await self.session.flush()

        catalog_threads = [t for t in catalog.get("threads", []) if t.get("num")]
        current_ids = {int(t["num"]) for t in catalog_threads}
        print(f"   В каталоге /{board_slug}: {len(catalog_threads)} тредов")

        stale_before = datetime.utcnow() - timedelta(hours=settings.STALE_SCAN_HOURS)
        queued = 0
        for t in catalog_threads:
            thread_id = int(t["num"])
            posts_count = int(t.get("posts_count") or 0)
            files_count = int(t.get("files_count") or 0)
            meta = self._thread_meta(t)

            state = await self.thread_state_repo.get_by_board_thread(board.id, thread_id)
            is_new = state is None
            if is_new:
                # Режим доски: all — новые треды парсим, selected — только включённые вручную
                parse_new = board.parse_mode == "all"
                state = ThreadState(
                    board_id=board.id,
                    thread_id=thread_id,
                    external_id=str(thread_id),  # у 2ch внешний id = номер треда
                    posts_count=posts_count,
                    files_count=files_count,
                    is_active=True,
                    parse_enabled=parse_new,
                    pending_scan=parse_new,
                    pending_reason="новый" if parse_new else None,
                    subject=meta["subject"],
                    comment=meta["comment"],
                    thread_timestamp=meta["thread_timestamp"],
                )
                self.session.add(state)
            else:
                state.is_active = True

            # Актуализируем метаданные треда (subject/comment/time) каждый цикл
            if meta["subject"]:
                state.subject = meta["subject"]
            if meta["comment"]:
                state.comment = meta["comment"]
            if meta["thread_timestamp"]:
                state.thread_timestamp = meta["thread_timestamp"]

            # Просмотры треда (из каталога) — обновляем каждый цикл, дёшево
            state.views_count = int(t.get("views") or 0)

            # Тред найден в каталоге — снимаем «промахи» (гигиена обхода):
            # тред вернулся (или никуда не пропадал) — счётчик мёртвых сбрасываем.
            state.misses = 0
            state.missing_since = None

            if not state.parse_enabled:
                # Тред отключён в админке: счётчики каталога не переносим, чтобы
                # при включении парсинга он снова попал в очередь (появившиеся
                # файлы), и не тратим на него каталог второй раз.
                continue

            # Очередь на докачку. Приоритет задаёт фаза B: «новый»/«изменения»/
            # «файлы» — свежие, «просрочен»/«не скачивался» — плановый догон.
            # Уже помеченную свежую причину не перебиваем.
            if is_new:
                pass  # помечен как «новый» при создании
            elif state.posts_count != posts_count or state.files_count != files_count:
                state.pending_scan = True
                state.pending_reason = "изменения"
            elif state.last_scanned_at is None:
                state.pending_scan = True
                state.pending_reason = state.pending_reason or "не скачивался"
            elif state.last_scanned_at < stale_before:
                state.pending_scan = True
                state.pending_reason = state.pending_reason or "просрочен"

            # Счётчики каталога — источник истины для «есть ли новые файлы»
            state.posts_count = posts_count
            state.files_count = files_count
            if state.pending_scan:
                queued += 1

        # Треды, исчезнувшие из каталога: считаем промахи и гасим не сразу.
        # Каталог 2ch иногда отдаётся обрезанным — мгновенное is_active=False
        # прятало живые треды и с сайта, и из админки. Теперь тред выключается
        # только после DEAD_THREAD_AFTER_MISSES проходов подряд, а в админке
        # у него видно misses/missing_since (фильтры «Мёртвые»/«Просроченные»).
        all_states = await self.thread_state_repo.get_all_by_board(board.id)
        missing = noted = deactivated = 0
        for st in all_states:
            if st.thread_id in current_ids:
                continue
            missing += 1
            st.misses = int(st.misses or 0) + 1
            if st.missing_since is None:
                st.missing_since = datetime.utcnow()
                noted += 1
            if st.is_active and st.misses >= settings.DEAD_THREAD_AFTER_MISSES:
                st.is_active = False
                deactivated += 1
        if missing:
            print(
                f"   [miss] Нет в каталоге тредов: {missing} "
                f"(впервые отмечено: {noted}, отключено: {deactivated})"
            )

        await self.session.commit()
        await self._clear_progress()
        print(
            f"[ok] Каталог /{board_slug}: тредов {len(catalog_threads)}, "
            f"в очереди {queued}"
        )
        return len(catalog_threads)

    async def build_scan_plan(self) -> List[Tuple[str, int, str]]:
        """Фаза A по всем доскам + очередь докачки из БД.

        Сначала дёшево обновляются каталоги всех парсируемых досок (1 запрос на
        доску), затем строится очередь: свежие изменения и новые треды вперёд,
        дальше — по «давности» сканирования (LRU). Очередь хранится в БД
        (`pending_scan`), поэтому перезапуск процесса её не теряет.
        """
        board_slugs = await self.board_repo.get_parsable_slugs()
        print(f"[list] Доски для парсинга: {', '.join(board_slugs) or '— (нет)'}")
        for board_slug in board_slugs:
            if self.stop_check is not None and await self.stop_check():
                print("[stop] Остановка по команде из админки")
                return []
            await self.sync_board_catalog(board_slug)
            await asyncio.sleep(settings.REQUEST_DELAY)

        queue = await self.thread_state_repo.get_scan_queue()
        plan = self._interleave_by_board(queue)
        fresh = sum(1 for _, _, reason in queue if reason in FRESH_REASONS)
        print(f"[plan] Очередь на докачку: {len(plan)} тредов (свежих: {fresh})")
        return plan

    @staticmethod
    def _interleave_by_board(
        queue: List[Tuple[str, int, str]],
    ) -> List[Tuple[str, int, str]]:
        """Round-robin по доскам: длинная очередь одной доски не держит другие.

        Внутри каждой доски порядок сохраняется (свежие изменения → LRU), но
        между досками проход чередуется, поэтому ни одна доска не ждёт часами,
        пока разберут очередь соседней.
        """
        by_board: Dict[str, List[Tuple[str, int, str]]] = {}
        for item in queue:
            by_board.setdefault(item[0], []).append(item)

        plan: List[Tuple[str, int, str]] = []
        index = 0
        while True:
            added = False
            for slug in by_board:
                bucket = by_board[slug]
                if index < len(bucket):
                    plan.append(bucket[index])
                    added = True
            if not added:
                break
            index += 1
        return plan

    async def scan_thread(self, board_slug: str, thread_id: int, reason: str = "") -> bool:
        """Фаза B: докачивает новые файлы одного треда.

        Возвращает True, если проход завершён полностью (тред снят с очереди).
        При остановке из админки или ошибке загрузки списка файлов флаг
        `pending_scan` остаётся — тред докачается в следующем цикле, а уже
        сохранённые файлы отсеются по md5 без повторного скачивания.
        """
        board = await self.board_repo.get_by_slug(board_slug)
        if board is None:
            print(f"   [err] Доска /{board_slug} не найдена в БД")
            return False
        state = await self.thread_state_repo.get_by_board_thread(board.id, thread_id)
        if state is None:
            print(f"   [err] Тред {thread_id} не найден в БД")
            return False
        if not state.parse_enabled or not state.is_active:
            # Пока тред ждал очереди, его выключили в админке
            print(f"   [skip]  Тред {thread_id} — снят с парсинга, пропускаю")
            return False

        # Попытку фиксируем сразу: видно в админке и не теряется при сбое
        state.last_scan_attempt_at = datetime.utcnow()
        await self.session.commit()

        all_files = await self.fetch_thread_files(board_slug, thread_id)
        if all_files is None:
            # Список файлов не получен — тред остаётся в очереди
            print(f"   [err] Тред {thread_id}: не удалось получить список файлов")
            await self._clear_progress()
            return False

        # «Файлов на форуме» считаем по всему треду и независимо от режима прохода,
        # поэтому метрика «Недокачано» не зависит от инкрементального среза.
        state.files_detected = sum(
            1
            for meta in all_files
            if MediaValidator.is_allowed(
                meta["filename"],
                meta["size_bytes"],
                meta["media_type"],
                meta.get("width"),
                meta.get("height"),
            )[0]
        )

        # Инкрементальный проход: частые сканы по причине «изменения» обрабатывают
        # только посты новее `last_post_num`, если прошлый проход был без наших
        # ошибок. Плановый догон («просрочен»), «недокачано» («файлы»), «вручную» и
        # первый проход идут полным обходом — так повторяются неудавшиеся загрузки
        # и подхватываются правки старых постов.
        files = all_files
        skipped_old = 0
        incremental = (
            reason == "изменения"
            and state.last_post_num is not None
            and int(state.last_scan_errors or 0) == 0
        )
        if incremental:
            last_num = int(state.last_post_num or 0)
            files = [
                meta for meta in all_files if int(meta.get("post_num") or 0) > last_num
            ]
            skipped_old = len(all_files) - len(files)

        # Точечная сверка: файлы, уже сохранённые в этом треде с объектом в S3,
        # отсеиваем **одним** запросом (условие совпадает с веткой `[have]`), иначе
        # полный проход по треду на 800+ файлов делает по запросу на каждый файл.
        saved_md5 = await self.media_repo.saved_md5_in_thread(board.id, thread_id)
        already_saved = sum(1 for meta in files if meta["md5"] in saved_md5)
        if already_saved:
            files = [meta for meta in files if meta["md5"] not in saved_md5]
            statuses_initial = {"have": already_saved}
            print(
                f"   [skip] Уже сохранено в треде: {already_saved} файлов "
                f"(сверка одним запросом, повторно не проверяем)"
            )
        else:
            statuses_initial = {}

        files_total = len(files)
        print(
            f"   [thread] Тред {thread_id} ({reason or 'очередь'}): {files_total} файлов"
            + (
                f" (только посты после #{state.last_post_num}, пропущено старых: {skipped_old})"
                if skipped_old
                else ""
            )
        )
        await self._progress(
            board_slug=board_slug,
            phase="files",
            thread_id=thread_id,
            files_total=files_total,
            files_done=0,
        )

        files_done = 0
        statuses: Dict[str, int] = dict(statuses_initial)
        # Пачки файлов: при MAX_PARALLEL_DOWNLOADS > 1 скачивание идёт параллельно
        # (`_prefetch_batch`).
        batch_size = max(1, int(settings.MAX_PARALLEL_DOWNLOADS))
        # Окно тяжёлой стадии: пока для следующих файлов идёт подготовка, уже
        # подготовленные выгружаются в S3 (и строятся деривативы) параллельно.
        # Запись в БД делает только основной цикл — сессия одна, поэтому
        # конкурентных flush не бывает (при MAX_PARALLEL_UPLOADS=1 поведение
        # прежнее: подготовка → S3 → запись по одному файлу).
        upload_workers = max(1, int(settings.MAX_PARALLEL_UPLOADS))
        window: List[Tuple[PreparedFile, "asyncio.Task[Dict[str, object]]"]] = []

        async def account(status: str) -> None:
            """Учитывает результат файла: сводка, прогресс, периодический коммит."""
            nonlocal files_done
            statuses[status] = statuses.get(status, 0) + 1
            files_done += 1
            await self._progress(
                board_slug=board_slug,
                phase="files",
                thread_id=thread_id,
                files_total=files_total,
                files_done=files_done,
            )
            every = settings.DB_COMMIT_EVERY_FILES
            if every > 0 and files_done % every == 0:
                await self.session.commit()
                print(
                    f"   [db]   Коммит: сохранено {files_done}/{files_total} "
                    f"файлов треда {thread_id}"
                )

        async def drain_one() -> None:
            """Дописывает в БД самый старый файл окна (его S3-стадия уже идёт)."""
            prepared_item, task_item = window.pop(0)
            payload = await task_item
            await account(await self._write_media(board, state, prepared_item, payload))

        try:
            for start in range(0, len(files), batch_size):
                batch = files[start : start + batch_size]
                prefetched = (
                    await self._prefetch_batch(batch, board, state)
                    if batch_size > 1
                    else {}
                )
                for meta in batch:
                    # Быстрая реакция на «Остановить» — проверяем между файлами
                    if self.stop_check is not None and await self.stop_check():
                        while window:  # докачиваем уже начатые выгрузки
                            await drain_one()
                        await self.session.commit()  # сохраняем уже скачанное
                        print("   [stop] Докачка прервана командой из админки")
                        fresh = await self.thread_state_repo.get_by_board_thread(
                            board.id, thread_id
                        )
                        if fresh is not None:
                            fresh.last_scan_note = (
                                f"прервано: остановлено вручную "
                                f"({files_done}/{files_total} файлов)"
                            )[:255]
                            await self.session.commit()
                        await self._clear_progress()
                        return False

                    prepared = await self._prepare_file(
                        board, state, meta, file_data=prefetched.get(meta["md5"])
                    )
                    if isinstance(prepared, str):
                        # Файл обрабатывать не нужно (have/dup/invalid/filtered/err)
                        await account(prepared)
                    else:
                        window.append(
                            (
                                prepared,
                                asyncio.create_task(
                                    self._run_upload(board, state, prepared)
                                ),
                            )
                        )
                        while len(window) >= upload_workers:
                            await drain_one()

                    # В последовательном режиме паузим между файлами (в параллельном
                    # темп задаёт `_prefetch_batch`: `REQUEST_DELAY` перед запросом)
                    if batch_size == 1 and upload_workers == 1:
                        await asyncio.sleep(settings.REQUEST_DELAY * 0.5)

            while window:  # добираем хвост окна
                await drain_one()

            # Проход завершён — снимаем тред с очереди и пишем итог для админки
            note = (
                f"новых {statuses.get('saved', 0)}, уже было {statuses.get('have', 0)}, "
                f"дублей {statuses.get('dup', 0)}, битых {statuses.get('invalid', 0)}, "
                f"отфильтровано {statuses.get('filtered', 0)}, ошибок {statuses.get('err', 0)}"
            )
            suffixes = []
            if skipped_old:
                suffixes.append(f"пропущено старых: {skipped_old}")
            if already_saved:
                suffixes.append(f"уже сохранено: {already_saved}")
            if suffixes:
                note += " (" + ", ".join(suffixes) + ")"
            print(f"   [done] Тред {thread_id}: {note}")
            state.last_scan_note = note[:255]
            state.last_scan_errors = int(statuses.get("err", 0))
            max_post = max((int(meta.get("post_num") or 0) for meta in all_files), default=0)
            if max_post > 0:
                state.last_post_num = max_post
            state.pending_scan = False
            state.pending_reason = None
            state.last_scanned_at = datetime.utcnow()
            await self.session.commit()
            return True
        except Exception as e:  # noqa: BLE001
            # Тред не должен ронять весь цикл: он остаётся в очереди и
            # докачается в следующем цикле (сохранённое отсеется по md5/sha).
            print(f"   [err] Тред {thread_id} прерван ({files_done}/{files_total}): {e}")
            await self.session.rollback()
            await self._clear_progress()
            await self._mark_scan_failed(board.id, thread_id, e)
            return False

    async def _mark_scan_failed(self, board_id: int, thread_id: int, error: Exception) -> None:
        """Записывает итог сбоя прохода: следующий проход уйдёт полным.

        `last_scan_errors > 0` заставляет следующий скан перебрать весь тред, а не
        только новые посты, — так проблемные файлы не теряются, а админ видит
        причину в строке треда.
        """
        try:
            fresh = await self.thread_state_repo.get_by_board_thread(board_id, thread_id)
            if fresh is None:
                return
            fresh.last_scan_errors = max(1, int(fresh.last_scan_errors or 0))
            fresh.last_scan_note = f"прервано: {error}"[:255]
            await self.session.commit()
        except Exception as inner:  # noqa: BLE001 — диагностика не должна мешать циклу
            print(f"   [warn] Не удалось записать итог сбоя треда {thread_id}: {inner}")

    # ───────────────────── Обработка файла ─────────────────────

    async def _prefetch_batch(
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
                data = await self.downloader.download(meta["file_url"])
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

    async def _prepare_file(
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
                file_data = await self.downloader.download(meta["file_url"])
                if not file_data:
                    return "err"

            # 4. Целостность: md5 из API должен совпасть с фактическим
            #    (CDN может пережимать картинки, поэтому для image не фатально)
            file_md5 = MediaValidator.compute_md5(file_data)
            integrity_ok = file_md5 == meta["md5"]
            if not integrity_ok and meta["media_type"] == "video":
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

    async def _upload_file(
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
            variants, duration_seconds = await self._build_variants(
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

    async def _run_upload(
        self, board: Board, thread_state: ThreadState, prepared: PreparedFile
    ) -> Dict[str, object]:
        """Обёртка стадии 2 для параллельного окна: ошибка не роняет тред."""
        try:
            return await self._upload_file(board, thread_state, prepared)
        except Exception as e:  # noqa: BLE001
            print(
                f"   [err] Ошибка выгрузки {prepared.meta.get('original_name', '?')}: {e}"
            )
            return {}

    async def _write_media(
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
        try:
            # Новую строку создаём только для новых файлов, а запись без объекта в
            # S3 (например, прошлый раз не докачали) обновляем — так повторные
            # проходы не размножают строки.
            async with self.session.begin_nested():
                if same_thread is not None:
                    media = same_thread
                    media.original_name = meta["original_name"]
                    media.source_url = meta["file_url"]
                    media.local_path = storage_path
                    media.file_hash = file_sha256
                    media.file_size = meta["size_bytes"]
                    media.mime_type = meta["mime_type"]
                    media.media_type = meta["media_type"]
                    media.width = meta.get("width")
                    media.height = meta.get("height")
                    if s3_key:
                        media.s3_bucket = settings.storage_bucket
                        media.s3_key = s3_key
                    if variants:
                        media.variants = variants
                    if duration_seconds:
                        media.duration_seconds = duration_seconds
                    media.download_status = "uploaded" if s3_key else "downloaded"
                    media.is_active = True
                    media.is_premium = bool(board.is_premium or thread_state.is_premium)
                    await self.session.flush()
                else:
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
                        s3_bucket=settings.storage_bucket if s3_key else None,
                        s3_key=s3_key,
                        variants=variants,
                        duration_seconds=duration_seconds,
                        width=meta.get("width"),
                        height=meta.get("height"),
                        download_status="uploaded" if s3_key else "downloaded",
                        is_visible=True,
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
        prepared = await self._prepare_file(board, thread_state, meta, file_data)
        if isinstance(prepared, str):
            return prepared
        payload = await self._run_upload(board, thread_state, prepared)
        return await self._write_media(board, thread_state, prepared, payload)

    async def _build_variants(
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
            )
        except Exception as e:  # noqa: BLE001
            print(f"   [warn] деривативы не построены ({meta.get('original_name', '?')}): {e}")
            return None, None
        if variants:
            print(f"   [img]  Деривативы: {', '.join(variants.keys())}")
        return variants, duration

    # ───────────────────── Reconciliation ─────────────────────

    async def run_reconciliation(self) -> None:
        """Сверка БД с локальным кэшем и S3 (актуальность данных и хранилища)."""
        print("[sync] Запуск сверки данных (reconciliation)...")
        service = ReconciliationService(self.session, self.storage, self.s3_storage)
        await service.run()