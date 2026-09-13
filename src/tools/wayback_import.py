# src/tools/wayback_import.py
"""Архивный импортёр раздела из веб-архива (Wayback Machine).

Зачем: часть разделов 2ch сейчас недоступна вживую (движок отдаёт 500), но каталог
и медиафайлы сохранились в Wayback. Инструмент обходит архив, скачивает медиа,
заливает его в наш S3 и создаёт обычные записи `boards` / `threads_state` / `media` —
то есть раздел появляется на сайте как любой другой, только наполняется не парсером,
а один раз из архива.

Как устроено:
* метаданные (тема треда, просмотры, число постов, размеры и md5 файлов) берём из
  архивного `catalog.json` — того же формата, что отдаёт живой 2ch;
* список файлов — из CDX API архива (`/cdx/search/cdx`, статус 200, без дублей);
* сам файл скачивается как снапшот (`/<timestamp>im_/<url>`) — это оригинальные
  байты без архивных вставок;
* ключ оригинала и деривативы формируются так же, как в конвейере парсера
  (`board_{id}/thread_{id}/{имя}` и `..._{sha12}_{kind}.webp`), поэтому сайт отдаёт
  импорт точно так же, как обычный контент;
* дедуп по SHA-256: повторный запуск ничего не задваивает, а найденный двойник
  превращается в «ссылку» на канонический файл (`duplicate_of_id`).

Пример запуска (в контейнере api):
    docker compose -f docker-compose.prod.yml exec -T api \
        python -m src.tools.wayback_import --board e --limit 50 --dry-run
    ... --board e --visible --delay 1.5        # боевой прогон
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from src.core.config import settings
from src.core.db import async_session_factory
from src.core.models import Board, Media, Source, ThreadState
from src.repositories.media_repo import MediaRepository
from src.services.derivatives import generate_and_upload
from src.services.media_validator import MediaValidator
from src.services.s3_storage import S3Storage

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
CDX_API = "https://web.archive.org/cdx/search/cdx"
ARCHIVE_WEB = "https://web.archive.org/web"
# Паттерн файла раздела: /e/src/<thread>/<name>
SRC_RE = re.compile(r"^/([a-z0-9_]+)/src/(\d+)/([^/?#]+)$")
IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
VIDEO_EXTS = {"mp4", "webm", "mkv"}


@dataclass
class CatalogFile:
    """Файл из архивного каталога: метаданные, которые отдал бы живой источник."""

    path: str
    name: str
    size: int = 0
    width: Optional[int] = None
    height: Optional[int] = None
    md5: Optional[str] = None
    order: int = 0
    media_type: str = "image"


@dataclass
class CatalogThread:
    """Тред из архивного каталога (тема, счётчики, файлы)."""

    num: int
    subject: Optional[str] = None
    posts_count: int = 0
    views_count: int = 0
    files: List[CatalogFile] = field(default_factory=list)


@dataclass
class Snapshot:
    """Снапшот архива: адрес оригинала и время сохранения."""

    timestamp: str
    url: str
    length: int = 0


@dataclass
class Stats:
    """Итог прогона: что скачали, что пропустили, где ошиблись."""

    files_seen: int = 0
    downloaded: int = 0
    created: int = 0
    duplicated: int = 0
    skipped: int = 0
    missing: int = 0
    errors: int = 0
    bytes_saved: int = 0


# ─────────────────────────── HTTP к архиву ───────────────────────────


def _http_get(url: str, *, timeout: int = 120, attempts: int = 4, accept: str = "*/*") -> Optional[bytes]:
    """Синхронный GET с повторами: архив часто отвечает 429 при частых запросах.

    Возвращает байты (снимая gzip) либо None. Все ошибки печатаются — прогон
    длинный, по логу должно быть видно, что именно не получилось.
    """
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": accept,
                    "Accept-Encoding": "identity",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                blob = resp.read()
                encoding = (resp.headers.get("Content-Encoding") or "").lower()
            if encoding == "gzip" or blob[:2] == b"\x1f\x8b":
                try:
                    blob = gzip.decompress(blob)
                except Exception:  # noqa: BLE001
                    pass
            return blob
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            # 404 — снапшота нет, повторять бессмысленно
            if exc.code == 404:
                return None
            time.sleep(min(30, 3 * attempt))
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            time.sleep(min(30, 3 * attempt))
    print(f"   [err]  архив не ответил ({last_error}): {url}")
    return None


def _http_get_json(url: str, **kwargs) -> Any:
    """GET + разбор JSON (пустой ответ → None)."""
    blob = _http_get(url, **kwargs)
    if not blob:
        return None
    try:
        return json.loads(blob.decode("utf-8", "replace") or "[]")
    except Exception as exc:  # noqa: BLE001
        print(f"   [err]  не JSON от архива: {exc}")
        return None


def cdx_snapshots(host: str, path: str, board: str, limit: int, delay: float) -> List[Snapshot]:
    """Список снапшотов со статусом 200 (по одному на URL, свежие первыми).

    `collapse=urlkey` убирает повторные сохранения одного адреса, а
    `filter=statuscode:200` — редиректы и ошибки архива.
    """
    query = urllib.parse.urlencode(
        {
            "url": f"{host}/{board}/{path}",
            "output": "json",
            "filter": "statuscode:200",
            "collapse": "urlkey",
            "limit": str(limit),
        }
    )
    rows = _http_get_json(f"{CDX_API}?{query}", timeout=180, accept="application/json")
    snapshot_list: List[Snapshot] = []
    if isinstance(rows, list) and len(rows) > 1:
        header, *data = rows
        for row in data:
            record = dict(zip(header, row))
            original = record.get("original") or ""
            if not original.startswith("http"):
                original = "https://" + original.lstrip("/")
            snapshot_list.append(
                Snapshot(
                    timestamp=str(record.get("timestamp") or ""),
                    url=original,
                    length=int(record.get("length") or 0),
                )
            )
    time.sleep(delay)
    return snapshot_list


def fetch_snapshot(snapshot: Snapshot, *, delay: float) -> Optional[bytes]:
    """Скачивает снапшот: `im_` — оригинальные байты без архивной обвязки."""
    url = f"{ARCHIVE_WEB}/{snapshot.timestamp}im_/{snapshot.url}"
    blob = _http_get(url, timeout=300)
    time.sleep(delay)
    return blob


# ─────────────────────── Метаданные из каталога ───────────────────────


def index_catalog(payload: Dict[str, Any]) -> Dict[str, CatalogThread]:
    """Каталог → треды с файлами и метаданными (ключ — номер треда)."""
    threads: Dict[str, CatalogThread] = {}
    for thread in payload.get("threads") or []:
        num = thread.get("num")
        if not num:
            continue
        entry = CatalogThread(
            num=int(num),
            subject=(thread.get("subject") or "").strip() or None,
            posts_count=int(thread.get("posts_count") or 0),
            views_count=int(thread.get("views") or thread.get("views_count") or 0),
        )
        for position, raw in enumerate(thread.get("files") or [], start=1):
            path = raw.get("path")
            if not path:
                continue
            name = raw.get("name") or path.rsplit("/", 1)[-1]
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            entry.files.append(
                CatalogFile(
                    path=path,
                    name=name,
                    size=int(raw.get("size") or 0) * 1024,  # в каталоге размер в КБ
                    width=raw.get("width"),
                    height=raw.get("height"),
                    md5=raw.get("md5"),
                    order=position,
                    # type=4 у 2ch — видео, остальное считаем картинками
                    media_type="video" if raw.get("type") == 4 or ext in VIDEO_EXTS else "image",
                )
            )
        threads[str(num)] = entry
    print(
        f"   [ok]   каталог: тредов {len(threads)}, "
        f"файлов {sum(len(t.files) for t in threads.values())}"
    )
    return threads


def fetch_catalog(
    board_slug: str, hosts: List[str], delay: float
) -> Tuple[Dict[str, CatalogThread], Optional[str]]:
    """Берёт самый свежий архивный `catalog.json` раздела и разбирает его.

    Ищем по нескольким хостам (2ch.hk, 2ch.su) — база у них одна, но снапшоты
    сохранились в разное время. Возвращает (треды по номерам, время снапшота).
    """
    for host in hosts:
        snapshots = cdx_snapshots(host, "catalog.json", board_slug, limit=50, delay=delay)
        for snapshot in reversed(snapshots):  # свежие в конце списка — берём их первыми
            blob = _http_get(f"{ARCHIVE_WEB}/{snapshot.timestamp}id_/{snapshot.url}", timeout=180)
            if not blob:
                continue
            try:
                payload = json.loads(blob.decode("utf-8", "replace"))
            except Exception as exc:  # noqa: BLE001
                print(f"   [warn] каталог {host} не разобрался: {exc}")
                continue
            print(f"   [ok]   каталог взят из архива: {host}, снапшот {snapshot.timestamp}")
            return index_catalog(payload), snapshot.timestamp
    print("   [warn] архивный каталог раздела не найден — метаданные будут пустыми")
    return {}, None


# ─────────────────────────── Импорт файла ───────────────────────────


async def import_file(
    session,
    s3: S3Storage,
    repo: MediaRepository,
    board: Board,
    thread: ThreadState,
    snapshot: Snapshot,
    meta_file: Optional[CatalogFile],
    *,
    visible: bool,
    premium: bool,
    delay: float,
    dry_run: bool,
    stats: Stats,
) -> None:
    """Скачивает снапшот файла, заливает в S3 и создаёт запись `media`.

    Идемпотентно: повторный запуск видит уже сохранённый файл (по md5 в треде или
    по SHA-256) и не задваивает ни галерею, ни объект в бакете.
    """
    # Путь файла в источнике: /e/src/<thread>/<name>
    match = SRC_RE.search(urllib.parse.urlparse(snapshot.url).path)
    if not match:
        return
    thread_num = int(match.group(2))
    file_name = urllib.parse.unquote(match.group(3))
    media_type = "video" if file_name.rsplit(".", 1)[-1].lower() in VIDEO_EXTS else "image"

    blob = fetch_snapshot(snapshot, delay=delay)
    if not blob:
        stats.missing += 1
        print(f"   [miss] снапшота нет: {file_name}")
        return
    stats.downloaded += 1
    stats.bytes_saved += len(blob)

    if media_type == "image":
        ok, err = MediaValidator.verify_image(blob)
        if not ok:
            stats.errors += 1
            print(f"   [del]  битое изображение {file_name}: {err}")
            return

    md5 = MediaValidator.compute_md5(blob)
    sha256 = MediaValidator.compute_sha256(blob)
    size = len(blob)

    if dry_run:
        stats.created += 1
        print(f"   [dry]  {file_name}: {size} байт, {media_type}, thread {thread_num}")
        return

    # 1. Этот же файл уже есть в этом треде — второй раз не сохраняем
    same = await repo.get_by_board_thread_md5(board.id, thread_num, md5)
    if same is not None and same.s3_key:
        stats.skipped += 1
        return

    # 2. Такой контент уже лежит в бакете (другой тред/доска) — делаем ссылку
    twin = await repo.get_by_hash(sha256)
    remote_key = f"board_{board.id}/thread_{thread_num}/{file_name}"
    variants = None
    duration = None
    s3_key = None

    async with session.begin_nested():
        if twin is not None and twin.s3_key:
            media = await repo.create(
                board_id=board.id,
                thread_id=thread_num,
                source_id=board.source_id,
                original_name=file_name,
                source_url=snapshot.url,
                source_md5=md5,
                file_size=size,
                mime_type=mime_for(file_name),
                media_type=media_type,
                width=(meta_file.width if meta_file else None),
                height=(meta_file.height if meta_file else None),
                s3_bucket=twin.s3_bucket,
                s3_key=twin.s3_key,
                variants=twin.variants,
                duration_seconds=twin.duration_seconds,
                duplicate_of_id=twin.id,
                source_order=(meta_file.order if meta_file else None),
                download_status=twin.download_status,
                is_visible=visible,
                is_active=True,
                is_premium=premium,
            )
            stats.duplicated += 1
            print(f"   [dup]  {file_name} → двойник ID {twin.id}")
        else:
            s3_key = await s3.upload_bytes(blob, remote_key, mime_for(file_name))
            if not s3_key:
                stats.errors += 1
                print(f"   [err]  не выгрузилось в S3: {file_name}")
                return
            tmp_dir = Path(tempfile.mkdtemp(prefix="wayback_"))
            tmp_path = tmp_dir / f"{sha256[:12]}.{file_name.rsplit('.', 1)[-1] or 'bin'}"
            tmp_path.write_bytes(blob)
            try:
                variants, duration = await generate_and_upload(
                    s3,
                    base_key=f"board_{board.id}/thread_{thread_num}/{sha256[:12]}",
                    media_type=media_type,
                    local_path=tmp_path,
                    file_data=blob if media_type == "image" else None,
                )
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

            media = await repo.create(
                board_id=board.id,
                thread_id=thread_num,
                source_id=board.source_id,
                original_name=file_name,
                source_url=snapshot.url,
                source_md5=md5,
                file_hash=sha256,
                file_size=size,
                mime_type=mime_for(file_name),
                media_type=media_type,
                width=(meta_file.width if meta_file else None),
                height=(meta_file.height if meta_file else None),
                s3_bucket=settings.storage_bucket,
                s3_key=s3_key,
                variants=variants,
                duration_seconds=duration,
                source_order=(meta_file.order if meta_file else None),
                download_status="uploaded",
                is_visible=visible,
                is_active=True,
                is_premium=premium,
            )
            stats.created += 1
            print(
                f"   [ok]   {file_name} ({size} байт, ID {media.id})"
                + (f", деривативы: {', '.join((variants or {}).keys())}" if variants else "")
            )
        await session.flush()

    if thread is not None:
        thread.files_count = int(thread.files_count or 0) + 1


# ─────────────────────────── Прогон импорта ───────────────────────────


async def import_board(args: argparse.Namespace) -> Stats:
    """Обходит архив раздела и наполняет сайт: S3 + `boards`/`threads_state`/`media`."""
    stats = Stats()
    s3 = S3Storage()
    if not s3.is_configured and not args.dry_run:
        print("[err] S3 не настроен — импорт невозможен (для проверки есть --dry-run)")
        return stats

    async with async_session_factory() as session:
        source = await ensure_source(
            session, args.source, "Архив Wayback Machine", "https://web.archive.org"
        )
        title = args.title or f"/{args.board} (архив Wayback)"
        board = await ensure_board(session, args.board, title, source, not args.hidden)
        await session.commit()

        threads_meta, catalog_ts = fetch_catalog(args.board, args.hosts, args.delay)
        if catalog_ts:
            print(f"   [ok]   метаданные каталога: снапшот {catalog_ts}")

        snapshots = cdx_snapshots(args.host, "src/*", args.board, args.limit, args.delay)
        print(f"   [ok]   снапшотов файлов найдено: {len(snapshots)}")
        if args.images_only:
            snapshots = [s for s in snapshots if s.url.rsplit(".", 1)[-1].lower() in IMAGE_EXTS]
        elif args.videos_only:
            snapshots = [s for s in snapshots if s.url.rsplit(".", 1)[-1].lower() in VIDEO_EXTS]
        print(f"   [ok]   к обработке: {len(snapshots)}")

        repo = MediaRepository(session)
        threads: Dict[int, ThreadState] = {}
        for position, snapshot in enumerate(snapshots, start=1):
            match = SRC_RE.search(urllib.parse.urlparse(snapshot.url).path)
            if not match:
                stats.skipped += 1
                continue
            thread_num = int(match.group(2))
            file_name = urllib.parse.unquote(match.group(3))
            meta_thread = threads_meta.get(str(thread_num))

            thread = threads.get(thread_num)
            if thread is None:
                thread = await ensure_thread(
                    session, board, thread_num, meta_thread, not args.hidden
                )
                await session.commit()
                threads[thread_num] = thread

            meta_file = None
            if meta_thread:
                meta_file = next((f for f in meta_thread.files if f.name == file_name), None)

            stats.files_seen += 1
            print(f"\n[{position}/{len(snapshots)}] /{args.board}/ тред {thread_num}: {file_name}")
            await import_file(
                session,
                s3,
                repo,
                board,
                thread,
                snapshot,
                meta_file,
                visible=not args.hidden,
                premium=args.premium,
                delay=args.delay,
                dry_run=args.dry_run,
                stats=stats,
            )
            if position % max(1, args.commit_every) == 0:
                await session.commit()

        await session.commit()
    return stats


# ─────────────────────────── CLI ───────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Аргументы запуска: что импортируем и насколько осторожно."""
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.wayback_import",
        description="Импорт раздела 2ch из веб-архива (Wayback Machine) в наш S3 и БД.",
    )
    parser.add_argument("--board", default="e", help="слаг раздела-источника (по умолчанию e)")
    parser.add_argument("--title", default="", help="название раздела на сайте")
    parser.add_argument("--source", default="wayback", help="код источника-архива в БД")
    parser.add_argument(
        "--host",
        default="2ch.su",
        help="хост, у которого берём медиафайлы (2ch.su — без Cloudflare)",
    )
    parser.add_argument(
        "--hosts",
        default="2ch.hk,2ch.su",
        help="хосты для поиска архивного catalog.json (через запятую)",
    )
    parser.add_argument("--limit", type=int, default=300, help="сколько файлов обработать (0 — все)")
    parser.add_argument("--delay", type=float, default=1.5, help="пауза между запросами к архиву, с")
    parser.add_argument("--commit-every", type=int, default=10, help="коммит каждые N файлов")
    parser.add_argument("--hidden", action="store_true", help="не показывать раздел публично")
    parser.add_argument("--premium", action="store_true", help="пометить файлы как премиум")
    parser.add_argument("--images-only", action="store_true", help="только изображения")
    parser.add_argument("--videos-only", action="store_true", help="только видео")
    parser.add_argument("--dry-run", action="store_true", help="скачать и посчитать, ничего не писать")
    return parser


def print_report(stats: Stats, args: argparse.Namespace) -> None:
    """Итог прогона одной таблицей — по нему видно, что и сколько залилось."""
    print("\n" + "=" * 62)
    print(f"ИТОГ импорта /{args.board} ({'dry-run' if args.dry_run else 'боевой прогон'})")
    print(f"  просмотрено файлов : {stats.files_seen}")
    print(f"  скачано из архива  : {stats.downloaded} (~{stats.bytes_saved / 1_048_576:.1f} МБ)")
    print(f"  создано записей    : {stats.created}")
    print(f"  дублей по SHA-256  : {stats.duplicated}")
    print(f"  пропущено (уже есть): {stats.skipped}")
    print(f"  нет в архиве       : {stats.missing}")
    print(f"  ошибок             : {stats.errors}")
    print("=" * 62)


def main(argv: Optional[List[str]] = None) -> int:
    """Точка входа: `python -m src.tools.wayback_import --board e --limit 50`."""
    args = build_parser().parse_args(argv)
    if args.images_only and args.videos_only:
        print("[err] --images-only и --videos-only одновременно не имеют смысла")
        return 2
    args.hosts = [h.strip() for h in args.hosts.split(",") if h.strip()]
    try:
        stats = asyncio.run(import_board(args))
    except KeyboardInterrupt:
        print("\n[warn] прервано пользователем — уже залитые файлы остались в S3 и БД")
        return 130
    print_report(stats, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())





async def ensure_source(session, code: str, title: str, base_url: str) -> Source:
    """Источник-«архив»: по нему админка отделяет импортированное от живого."""
    source = (
        await session.execute(select(Source).where(Source.code == code))
    ).scalar_one_or_none()
    if source is None:
        source = Source(
            code=code,
            title=title,
            kind="html",
            base_url=base_url,
            config={},
            # В прогонах не участвует: наполняется только этим импортёром
            is_enabled=False,
            sort_order=90,
        )
        session.add(source)
        await session.flush()
        print(f"   [ok]   источник создан: {code} (id={source.id})")
    return source


async def ensure_board(session, slug: str, title: str, source: Source, visible: bool) -> Board:
    """Раздел архива: показываем публично, но парсер его не трогает."""
    board = (
        await session.execute(select(Board).where(Board.slug == slug))
    ).scalar_one_or_none()
    if board is None:
        board = Board(
            slug=slug,
            title=title,
            description="Импорт из веб-архива (Wayback Machine): раздел недоступен вживую.",
            source_id=source.id,
            is_visible=visible,
            parse_enabled=False,
        )
        session.add(board)
        await session.flush()
        print(f"   [ok]   раздел создан: /{slug} (id={board.id})")
    else:
        board.source_id = board.source_id or source.id
        board.is_visible = visible
        board.parse_enabled = False
        if title and (not board.title or board.title == board.slug):
            board.title = title
    return board


async def ensure_thread(
    session, board: Board, num: int, meta: Optional[CatalogThread], visible: bool
) -> ThreadState:
    """Тред раздела: тема и счётчики — из архивного каталога, если он есть."""
    thread = (
        await session.execute(
            select(ThreadState).where(
                ThreadState.board_id == board.id, ThreadState.thread_id == num
            )
        )
    ).scalar_one_or_none()
    if thread is None:
        thread = ThreadState(
            board_id=board.id,
            thread_id=num,
            external_id=str(num),
            is_active=True,
            is_visible=visible,
            parse_enabled=False,
            files_detected=len(meta.files) if meta else 0,
            last_scanned_at=datetime.utcnow(),
            last_scan_note="импорт из архива",
        )
        session.add(thread)
        await session.flush()
    if meta:
        thread.subject = meta.subject or thread.subject
        thread.posts_count = meta.posts_count or thread.posts_count
        thread.views_count = meta.views_count or thread.views_count
        thread.files_detected = len(meta.files) or thread.files_detected
    thread.is_visible = visible
    thread.is_active = True
    return thread


def mime_for(name: str) -> str:
    """MIME по расширению (для S3 Content-Type и карточек)."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in IMAGE_EXTS:
        return f"image/{'jpeg' if ext in {'jpg', 'jpeg'} else ext}"
    if ext in VIDEO_EXTS:
        return f"video/{'mp4' if ext in {'mp4', 'mkv'} else ext}"
    return "application/octet-stream"



