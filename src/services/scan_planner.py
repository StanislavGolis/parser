# src/services/scan_planner.py
"""План обхода источника: каталог → очередь → проход по «тредам».

Здесь живёт всё, что **не зависит от сайта**:

- `sync_board_catalog` — каталог раздела → строки `threads_state` и очередь
  `pending_scan` (с причинами), гигиена выпавших тредов (`misses`/`missing_since`),
  режим `parse_mode` (all | selected);
- `build_scan_plan` — фаза A по всем доскам источника + очередь докачки из БД;
- `scan_thread` — фаза B: файлы одного «треда» прогоняются через конвейер
  (`services/pipeline.py`), с инкрементом по постам, точечной сверкой и бюджетом;
- прогресс и живость — в Redis под ключами источника (`parser:{code}:*`).

Источник-специфичное (как читать каталог и файлы, какие заголовки нужны для
скачивания) — в адаптере: см. `src/parsers/base.py` и `src/parsers/dvach.py`.
Поэтому один планировщик обслуживает все источники, а «треды» источника
опознаются парой (доска, `external_id`): номер треда у 2ch, слаг записи у сайтов.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.models import Board, ThreadState
from src.parsers.base import CatalogResult, SourceAdapter
from src.repositories.board_repo import BoardRepository
from src.repositories.media_repo import MediaRepository
from src.repositories.thread_state_repo import FRESH_REASONS, ThreadStateRepository
from src.services import sources as sources_service
from src.services.catalog_health import mark_catalog_error, mark_catalog_ok
from src.services.media_validator import MediaValidator
from src.services.pipeline import FilePipeline, PreparedFile
from src.services.reconciliation import ReconciliationService

# Ограничение int4 — «синтетические» id тредов держим в его пределах
MAX_THREAD_ID = 2_147_483_647


def surrogate_thread_id(board_id: int, external_id: str) -> int:
    """Внутренний числовой id «треда» по внешнему идентификатору источника.

    У 2ch внешний id уже числовой (номер треда) — берём его как есть. У сайтов
    внешний id строковый (слаг записи): считаем стабильный числовой суррогат,
    чтобы публичный API и фильтры по `thread_id` работали без изменений.
    """
    if external_id.isdigit():
        return int(external_id)
    digest = hashlib.sha1(f"{board_id}:{external_id}".encode("utf-8")).hexdigest()
    return int(digest[:7], 16) % MAX_THREAD_ID or 1


class ScanPlanner:
    """Прогон одного источника: каталоги, очередь, проход по «тредам»."""

    def __init__(
        self,
        session: AsyncSession,
        adapter: SourceAdapter,
        source_code: str,
        source_id: Optional[int] = None,
        *,
        stop_check=None,
    ):
        self.session = session
        self.adapter = adapter
        self.source_code = source_code
        self.source_id = source_id
        # Callback «остановить прогон» (проверяется между досками и файлами)
        self.stop_check = stop_check

        self.board_repo = BoardRepository(session)
        self.thread_state_repo = ThreadStateRepository(session)
        self.media_repo = MediaRepository(session)
        # Конвейер файла: общий для всех источников, различие — только заголовки
        # скачивания (Referer/UA), которые сообщает адаптер
        self.pipeline = FilePipeline(session, download_headers=adapter.download_headers())

    # ── Прогресс и живость (ключи источника: parser:{code}:*) ─────────

    async def _progress(self, **fields) -> None:
        """Публикует прогресс прогона (админка источника опрашивает его)."""
        await sources_service.write_progress(
            self.source_code,
            {"updated_at": datetime.utcnow().isoformat(), **fields},
        )

    async def _clear_progress(self) -> None:
        await sources_service.clear_progress(self.source_code)

    async def stopped(self) -> bool:
        """Просили ли остановить прогон (кнопка в админке источника)."""
        if self.stop_check is None:
            return False
        return await self.stop_check()

    # ── Доски источника ───────────────────────────────────────────────

    async def ensure_configured_boards(self, slugs: List[str]) -> None:
        """Создаёт доски источника по списку из его конфигурации (первый запуск).

        Новые доски создаются выключенными (parse_enabled=False, is_visible=False):
        их включает админ. Если у источника уже есть хотя бы одна доска —
        автозаполнение пропускается, чтобы не возвращать удалённые вручную.
        """
        if not slugs:
            return
        print(f"[init] Источник {self.source_code}: проверка досок из конфигурации...")
        query = select(func.count()).select_from(Board)
        if self.source_id is not None:
            query = query.where(Board.source_id == self.source_id)
        cnt = (await self.session.execute(query)).scalar() or 0
        if cnt > 0:
            print("[init] Доски уже настроены в БД — автозаполнение пропущено")
            return

        for board_slug in slugs:
            catalog = await self.adapter.fetch_catalog(board_slug)
            if catalog is None:
                print(f"   [warn] Раздел /{board_slug} не ответил каталогом — пропускаю")
                continue
            board, created = await self.board_repo.get_or_create(
                slug=board_slug,
                defaults={
                    "title": catalog.title or board_slug.upper(),
                    "description": catalog.description,
                    "is_visible": False,
                    "parse_enabled": False,
                    **({"source_id": self.source_id} if self.source_id else {}),
                },
            )
            # Название с сайта берём только если его ещё не задали вручную в админке
            if catalog.title and (not board.title or board.title.lower() == board.slug):
                board.title = catalog.title
            if catalog.description and not board.description:
                board.description = catalog.description
            if self.source_id and not board.source_id:
                board.source_id = self.source_id
            await self.session.flush()
            print(f"   [ok] Доска /{board_slug} — {'создана' if created else 'уже в БД'}")

        await self.session.commit()



    # ── Фаза A: каталог раздела ───────────────────────────────────────

    async def sync_board_catalog(self, board_slug: str) -> Optional[int]:
        """Каталог раздела → метаданные «тредов» и очередь на докачку.

        Скачивается только каталог (один запрос на раздел), файлы — нет, поэтому
        все разделы источника обходятся за минуты. Возвращает число «тредов»
        в каталоге (`None` — каталог недоступен: сеть/ошибка сайта).
        """
        print(f"[info] Каталог /{board_slug} (источник {self.source_code})")
        await self._progress(board_slug=board_slug, phase="catalog")

        catalog: Optional[CatalogResult] = await self.adapter.fetch_catalog(board_slug)
        if catalog is None:
            # Раздел мог быть удалён на сайте (или изменилась вёрстка): фиксируем
            # в Redis, чтобы админка показала «каталог недоступен» на карточке.
            await mark_catalog_error(
                board_slug, "источник не отдал каталог (сеть/ошибка сайта) — раздел доступен?"
            )
            print(f"   [err] Не удалось получить каталог /{board_slug}")
            await self._clear_progress()
            return None
        await mark_catalog_ok(board_slug)

        board, _ = await self.board_repo.get_or_create(
            slug=board_slug,
            defaults={
                "title": catalog.title or board_slug.upper(),
                "is_visible": False,
                **({"source_id": self.source_id} if self.source_id else {}),
            },
        )
        if self.source_id and not board.source_id:
            board.source_id = self.source_id
        # Название/описание с сайта берём только если их не задали вручную в админке
        if catalog.title and (not board.title or board.title.lower() == board.slug):
            board.title = catalog.title
        if catalog.description and not board.description:
            board.description = catalog.description
        await self.session.flush()

        nodes = [node for node in catalog.threads if node.external_id]
        current_ids = {node.external_id for node in nodes}
        print(f"   В каталоге /{board_slug}: {len(nodes)} тредов")

        stale_before = datetime.utcnow() - timedelta(hours=settings.STALE_SCAN_HOURS)
        queued = 0
        for node in nodes:
            state = await self.thread_state_repo.get_by_board_external(
                board.id, node.external_id
            )
            is_new = state is None
            if is_new:
                # Режим доски: all — новые треды парсим, selected — только включённые вручную
                parse_new = board.parse_mode == "all"
                state = ThreadState(
                    board_id=board.id,
                    thread_id=surrogate_thread_id(board.id, node.external_id),
                    external_id=node.external_id,
                    posts_count=node.posts_count,
                    files_count=node.files_count,
                    fingerprint=node.fingerprint,
                    is_active=True,
                    parse_enabled=parse_new,
                    pending_scan=parse_new,
                    pending_reason="новый" if parse_new else None,
                    subject=node.subject,
                    comment=node.comment,
                    thread_timestamp=node.timestamp,
                )
                self.session.add(state)
            else:
                state.is_active = True

            # Актуализируем метаданные «треда» (subject/comment/time) каждый цикл
            if node.subject:
                state.subject = node.subject
            if node.comment:
                state.comment = node.comment
            if node.timestamp:
                state.thread_timestamp = node.timestamp

            # Просмотры треда (из каталога) — обновляем каждый цикл, дёшево
            state.views_count = int(node.views_count or 0)

            # Тред найден в каталоге — снимаем «промахи» (гигиена обхода):
            # тред вернулся (или никуда не пропадал) — счётчик мёртвых сбрасываем.
            state.misses = 0
            state.missing_since = None

            if not state.parse_enabled:
                # Тред отключён в админке: счётчики каталога не переносим, чтобы
                # при включении парсинга он снова попал в очередь (появившиеся файлы).
                continue

            # Очередь на докачку. Приоритет задаёт фаза B: «новый»/«изменения»/
            # «файлы» — свежие, «просрочен»/«не скачивался» — плановый догон.
            # Уже помеченную свежую причину не перебиваем.
            # Кроме счётчиков сравниваем fingerprint: сайты не отдают ни постов,
            # ни числа файлов, зато дают «отпечаток» записи (например, обложку).
            changed = (
                state.posts_count != node.posts_count
                or state.files_count != node.files_count
                or bool(node.fingerprint and state.fingerprint != node.fingerprint)
            )
            if is_new:
                pass  # помечен как «новый» при создании
            elif changed:
                state.pending_scan = True
                state.pending_reason = "изменения"
            elif state.last_scanned_at is None:
                state.pending_scan = True
                state.pending_reason = state.pending_reason or "не скачивался"
            elif state.last_scanned_at < stale_before:
                state.pending_scan = True
                state.pending_reason = state.pending_reason or "просрочен"

            # Счётчики каталога и отпечаток — источник истины для «есть ли новое»
            state.posts_count = node.posts_count
            state.files_count = node.files_count
            if node.fingerprint:
                state.fingerprint = node.fingerprint
            if state.pending_scan:
                queued += 1

        # Треды, исчезнувшие из каталога: считаем промахи и гасим не сразу.
        # Каталог источника иногда отдаётся обрезанным — мгновенное is_active=False
        # прятало живые треды и с сайта, и из админки. Теперь тред выключается
        # только после DEAD_THREAD_AFTER_MISSES проходов подряд, а в админке
        # у него видно misses/missing_since (фильтры «Мёртвые»/«Просроченные»).
        all_states = await self.thread_state_repo.get_all_by_board(board.id)
        missing = noted = deactivated = 0
        for st in all_states:
            if st.external_id in current_ids:
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
        print(f"[ok] Каталог /{board_slug}: тредов {len(nodes)}, в очереди {queued}")
        return len(nodes)

    # ── Фаза B: план обхода и проход по «тредам» ──────────────────────

    async def build_scan_plan(self) -> List[Tuple[str, int, str]]:
        """Фаза A по всем доскам источника + очередь докачки из БД.

        Сначала дёшево обновляются каталоги парсируемых досок **этого источника**
        (1 запрос на доску), затем строится очередь: свежие изменения и новые треды
        вперёд, дальше — по «давности» сканирования (LRU). Очередь хранится в БД
        (`pending_scan`), поэтому перезапуск процесса её не теряет, а прогоны
        разных источников независимы: каждый берёт только свои доски.
        """
        board_slugs = await self.board_repo.get_parsable_slugs(source_id=self.source_id)
        print(
            f"[list] Источник {self.source_code}: доски для парсинга: "
            f"{', '.join(board_slugs) or '— (нет)'}"
        )
        for board_slug in board_slugs:
            if await self.stopped():
                print("[stop] Остановка по команде из админки")
                return []
            await self.sync_board_catalog(board_slug)
            await asyncio.sleep(settings.REQUEST_DELAY)

        queue = await self.thread_state_repo.get_scan_queue(source_id=self.source_id)
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
        """Фаза B: докачивает новые файлы одного «треда».

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

        nodes = await self.adapter.fetch_thread_files(board_slug, state.external_id)
        if nodes is None:
            # Список файлов не получен — тред остаётся в очереди
            print(f"   [err] Тред {thread_id}: не удалось получить список файлов")
            await self._clear_progress()
            return False
        all_files = [node.as_meta() for node in nodes]

        # «Файлов на сайте» считаем по всему треду и независимо от режима прохода,
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
                    if await self.stopped():
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

    # ── Сверка данных ─────────────────────────────────────────────────

    async def run_reconciliation(self) -> None:
        """Сверка БД с локальным кэшем и S3 (актуальность данных и хранилища)."""
        print(f"[sync] Источник {self.source_code}: сверка данных (reconciliation)...")
        service = ReconciliationService(
            self.session, self.pipeline.storage, self.pipeline.s3_storage
        )
        await service.run()

