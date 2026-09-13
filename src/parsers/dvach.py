# src/parsers/dvach.py
"""Парсер 2ch.hk на JSON API (адаптер источника).

Источник-специфичное: HTTP/JSON 2ch и маппинг в общие структуры —
`catalog.json` → «треды», `res/{id}.json` → файлы треда (md5, size, width,
height доступны **до** скачивания, поэтому дедупликация идёт до загрузки).

Общее (скачивание, валидация, S3, деривативы, запись в БД, план обхода,
очередь, гигиена тредов) живёт в `services/pipeline.py` и остаётся неизменным
для любого источника: см. `services/sources.py` (реестр и флаги прогонов).
"""
import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import aiohttp
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.models import Board, ThreadState
from src.core.redis_client import redis_client
from src.services.pipeline import FilePipeline, PreparedFile
from src.repositories.board_repo import BoardRepository
from src.repositories.media_repo import MediaRepository
from src.repositories.thread_state_repo import FRESH_REASONS, ThreadStateRepository
from src.services.catalog_health import mark_catalog_error, mark_catalog_ok
from src.services.media_validator import MediaValidator
from src.services.reconciliation import ReconciliationService

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

        # Конвейер файла (подготовка → S3/деривативы → БД) живёт отдельно:
        # та же логика работает для любого источника (services/pipeline.py)
        self.pipeline = FilePipeline(session)

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
        # (`pipeline.prefetch_batch`).
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
            await account(await self.pipeline.write_media(board, state, prepared_item, payload))

        try:
            for start in range(0, len(files), batch_size):
                batch = files[start : start + batch_size]
                prefetched = (
                    await self.pipeline.prefetch_batch(batch, board, state)
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

                    prepared = await self.pipeline.prepare_file(
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
                                    self.pipeline.run_upload(board, state, prepared)
                                ),
                            )
                        )
                        while len(window) >= upload_workers:
                            await drain_one()

                    # В последовательном режиме паузим между файлами (в параллельном
                    # темп задаёт `pipeline.prefetch_batch`: `REQUEST_DELAY` перед запросом)
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

    # ───────────────────── Reconciliation ─────────────────────

    async def run_reconciliation(self) -> None:
        """Сверка БД с локальным кэшем и S3 (актуальность данных и хранилища)."""
        print("[sync] Запуск сверки данных (reconciliation)...")
        service = ReconciliationService(self.session, self.pipeline.storage, self.pipeline.s3_storage)
        await service.run()