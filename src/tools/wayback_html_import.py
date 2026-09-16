# src/tools/wayback_html_import.py
"""Импорт раздела 2ch из HTML-снапшотов веб-архива (когда нет JSON-каталога).

Зачем отдельный инструмент. `wayback_import` строит список файлов из архивного
`res/*.json` — это формат живого 2ch, и есть он в архиве далеко не для всех досок.
У закрытых разделов (например `/h` — «Хентай») JSON-каталогов в архиве нет вовсе:
сохранились только HTML-страницы тредов (`/h/res/14906.html`) и сами файлы
(`/h/src/1292049777386.jpg`). Этот импортёр собирает раздел из них.

Как устроено:
* список тредов — CDX-запрос по `/{board}/res/` (снапшоты HTML, статус 200);
* метаданные треда — из разметки вакабы: `id="post_{num}"`, тема в
  `<span class="subject">`, время в `data-utc` (UNIX — русский формат парсить не надо),
  число постов — по количеству `id="post_…"`;
* файлы — из блоков `<span class="filesize"><a href="/h/src/имя">имя</a> (<em>133Кб, 707x1000</em>)`:
  берём ссылку, имя, размер и разрешение;
* сам файл скачивается снапшотом `im_` (оригинальные байты): точный timestamp ищем в
  CDX, если не нашли — пробуем ближайший снапшот по году страницы;
* ключи в S3 и деривативы строятся как в конвейере парсера, поэтому сайт отдаёт импорт
  наравне с обычным контентом;
* дедуп по SHA-256: повторный запуск не задваивает, двойник становится ссылкой
  (`duplicate_of_id`).

Запуск (в контейнере api):
    docker compose -f docker-compose.prod.yml exec -T api \\
        python -m src.tools.wayback_html_import --board h --title Хентай \\
        --threads-limit 20 --dry-run
    ... --board h --title Хентай --premium          # боевой прогон
"""
from __future__ import annotations

import argparse
import asyncio
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
from typing import Dict, List, Optional

from sqlalchemy import select

from src.core.config import settings
from src.core.db import async_session_factory
from src.core.models import Board, Media, Source, ThreadState
from src.repositories.media_repo import MediaRepository
from src.services.derivatives import generate_and_upload
from src.services.media_validator import MediaValidator
from src.services.s3_storage import S3Storage
from src.tools.wayback_import import (
    UA,
    ensure_board,
    ensure_source,
    ensure_thread,
    mime_for,
)

CDX_API = "https://web.archive.org/cdx/search/cdx"
ARCHIVE = "https://web.archive.org/web"
IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
VIDEO_EXTS = {"mp4", "webm", "mkv", "avi", "mov", "m4v"}

# ── Разметка архивной страницы вакабы ────────────────────────────────
POST_ID_RE = re.compile(r'id="post_(\d+)"')
SUBJECT_RE = re.compile(r'<span class="subject">([^<]{2,200})</span>')
DATE_RE = re.compile(r'data-utc="(\d+)"')
FILE_RE = re.compile(
    # Между ссылкой и скобками с размерами в разметке вакабы стоит `&nbsp;`,
    # поэтому «пробельное» окружение включает и его.
    r'<a[^>]+href="(/[^"]*?/src/[^"]+)"[^>]*>([^<]+)</a>(?:&nbsp;|\s)*'
    r"\(<em>([^<]*)</em>\)"
)
SIZE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(Кб|КБ|кб|Мб|МБ|Kb|Mb)", re.IGNORECASE)
DIM_RE = re.compile(r"(\d{2,5})\s*[x×]\s*(\d{2,5})")


@dataclass
class FileRef:
    """Файл из разметки страницы: ссылка, имя, размер и разрешение."""

    url: str
    name: str
    size_bytes: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass
class ThreadRef:
    """Тред из CDX: номер, timestamp снапшота страницы и её оригинальный URL."""

    num: int
    timestamp: str
    url: str


@dataclass
class ParsedThread:
    """Что удалось прочитать со страницы треда."""

    num: int
    subject: Optional[str] = None
    posted_at: Optional[datetime] = None
    posts_count: int = 0
    files: List[FileRef] = field(default_factory=list)


@dataclass
class Stats:
    """Счётчики прогона — по ним строится итоговая таблица."""

    threads_seen: int = 0
    files_seen: int = 0
    downloaded: int = 0
    bytes_saved: int = 0
    created: int = 0
    duplicated: int = 0
    skipped: int = 0
    missing: int = 0
    errors: int = 0


def fetch(url: str, *, delay: float = 1.0, tries: int = 3) -> Optional[bytes]:
    """Скачивает URL из архива с паузой и повторами (архив частенько отвечает 5xx)."""
    for attempt in range(tries):
        time.sleep(delay)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(request, timeout=90) as response:
                if response.status == 200:
                    return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 403):
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
    return None


def cdx_threads(
    board: str, host: str, *, delay: float = 1.0, from_year: str = ""
) -> List[ThreadRef]:
    """Список HTML-снапшотов тредов раздела из CDX-индекса архива.

    `from_year` отсекает ранние снапшоты: для страниц 2012 года файлов в архиве
    обычно уже нет, поэтому боевой прогон выгоднее начинать с 2013.
    """
    query = (
        f"{CDX_API}?url={host}/{board}/res/&matchType=prefix&output=json"
        "&filter=statuscode:200&filter=mimetype:text/html&collapse=urlkey"
    )
    blob = fetch(query, delay=delay)
    if not blob:
        return []

    try:
        rows = json.loads(blob.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return []
    if not rows:
        return []

    head, *items = rows
    refs: List[ThreadRef] = []
    seen: set[int] = set()
    for item in items:
        row = dict(zip(head, item))
        match = re.search(r"/res/(\d+)\.html", row.get("urlkey", ""))
        if not match:
            continue
        timestamp = row.get("timestamp", "")
        if from_year and timestamp[:4] < from_year:
            continue
        num = int(match.group(1))
        if num in seen:
            continue
        seen.add(num)
        refs.append(ThreadRef(num=num, timestamp=timestamp, url=row.get("original", "")))
    refs.sort(key=lambda ref: ref.num)
    return refs


def parse_thread_page(html: str, num: int) -> ParsedThread:
    """Читает тему, дату, число постов и файлы из HTML-страницы треда."""
    parsed = ParsedThread(num=num)

    parsed.posts_count = len(POST_ID_RE.findall(html)) or 1

    subject = SUBJECT_RE.search(html)
    if subject:
        text = " ".join(subject.group(1).split())
        # В вакабе «///» означает «тема не задана»
        if text and text != "///":
            parsed.subject = text[:500]

    stamp = DATE_RE.search(html)
    if stamp:
        try:
            parsed.posted_at = datetime.utcfromtimestamp(int(stamp.group(1)))
        except (ValueError, OSError):
            parsed.posted_at = None

    seen: set[str] = set()
    for href, name, meta in FILE_RE.findall(html):
        clean = urllib.parse.unquote(name.strip())
        if not clean or clean in seen:
            continue
        seen.add(clean)
        ref = FileRef(url=href, name=clean)
        size = SIZE_RE.search(meta)
        if size:
            value = float(size.group(1).replace(",", "."))
            unit = size.group(2).lower()
            ref.size_bytes = int(value * (1024 if unit in ("кб", "kb") else 1024 * 1024))
        dims = DIM_RE.search(meta)
        if dims:
            ref.width, ref.height = int(dims.group(1)), int(dims.group(2))
        parsed.files.append(ref)
    return parsed


def looks_like_media(blob: bytes) -> bool:
    """Похожи ли байты на картинку/видео.

    Архив на запрос снапшота без точного timestamp отдаёт свою HTML-страницу
    («нет в архиве»), причём со статусом 200. Без этой проверки такая заглушка
    попадала в импорт как «битое изображение».
    """
    head = blob[:16]
    if head.startswith((b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"BM")):
        return True
    if head.startswith(b"RIFF"):
        return blob[8:12] in (b"WEBP", b"AVI ")
    if b"ftyp" in blob[:32]:
        return True
    return head.startswith(b"\x1aE\xdf\xa3")


def file_snapshot(path: str, *, year: Optional[str], delay: float) -> Optional[bytes]:
    """Байты файла из архива: точный снапшот из CDX, иначе ближайший по году.

    Каждый вариант проверяем на сигнатуру медиа: архив умеет отдавать HTML-заглушку
    с кодом 200, и без проверки она уходила дальше как «битый файл».
    """
    query = (
        f"{CDX_API}?url={path.lstrip('/')}&matchType=exact&output=json"
        "&filter=statuscode:200&limit=1"
    )
    blob = fetch(query, delay=delay, tries=2)
    if blob:
        try:
            rows = json.loads(blob.decode("utf-8", errors="replace"))
            if len(rows) > 1:
                row = dict(zip(rows[0], rows[1]))
                original, timestamp = row.get("original"), row.get("timestamp")
                if original and timestamp:
                    data = fetch(f"{ARCHIVE}/{timestamp}im_/{original}", delay=delay, tries=2)
                    if data and looks_like_media(data):
                        return data
        except json.JSONDecodeError:
            pass

    host_path = path if path.startswith("http") else f"http://{path.lstrip('/')}"
    for stamp in (f"{year}im_", "2im_"):
        data = fetch(f"{ARCHIVE}/{stamp}/{host_path}", delay=delay, tries=1)
        if data and looks_like_media(data):
            return data
    return None


async def import_file(
    session,
    s3: S3Storage,
    repo: MediaRepository,
    board: Board,
    thread_num: int,
    ref: FileRef,
    thread_url: str,
    *,
    visible: bool,
    premium: bool,
    video_web: bool,
    year: Optional[str],
    delay: float,
    dry_run: bool,
    stats: Stats,
) -> None:
    """Скачивает файл из архива, заливает в S3 и создаёт запись `media`."""
    ext = ref.name.rsplit(".", 1)[-1].lower() if "." in ref.name else ""
    media_type = "video" if ext in VIDEO_EXTS else "image"
    if media_type == "image" and ext not in IMAGE_EXTS:
        return

    if not dry_run:
        known = (
            await session.execute(
                select(Media.id).where(
                    Media.board_id == board.id,
                    Media.thread_id == thread_num,
                    Media.original_name == ref.name,
                    Media.s3_key.isnot(None),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if known is not None:
            stats.skipped += 1
            return

    blob = file_snapshot(ref.url, year=year, delay=delay)
    if not blob:
        stats.missing += 1
        print(f"   [miss] нет снапшота: {ref.name}")
        return
    stats.downloaded += 1
    stats.bytes_saved += len(blob)

    if media_type == "image":
        ok, err = MediaValidator.verify_image(blob)
        if not ok:
            stats.errors += 1
            print(f"   [del]  битое изображение {ref.name}: {err}")
            return

    md5 = MediaValidator.compute_md5(blob)
    sha256 = MediaValidator.compute_sha256(blob)
    size = len(blob)

    if dry_run:
        stats.created += 1
        print(f"   [dry]  {ref.name}: {size} байт, {media_type}, тред {thread_num}")
        return

    # 1. Тот же файл уже сохранён в этом треде — второй раз не качаем и не пишем
    same = await repo.get_by_board_thread_md5(board.id, thread_num, md5)
    if same is not None and same.s3_key:
        stats.skipped += 1
        return

    # 2. Такой контент уже есть в бакете — делаем ссылку на канонический файл
    twin = await repo.get_by_hash(sha256)
    remote_key = f"board_{board.id}/thread_{thread_num}/{ref.name}"
    variants: Optional[Dict[str, str]] = None
    duration: Optional[float] = None
    s3_key: Optional[str] = None

    async with session.begin_nested():
        if twin is not None and twin.s3_key:
            await repo.create(
                board_id=board.id,
                thread_id=thread_num,
                source_id=board.source_id,
                original_name=ref.name,
                source_url=thread_url,
                source_md5=md5,
                file_size=size,
                mime_type=mime_for(ref.name),
                media_type=media_type,
                width=ref.width,
                height=ref.height,
                s3_bucket=twin.s3_bucket,
                s3_key=twin.s3_key,
                variants=twin.variants,
                duration_seconds=twin.duration_seconds,
                duplicate_of_id=twin.id,
                download_status=twin.download_status,
                is_visible=visible,
                is_active=True,
                is_premium=premium,
            )
            stats.duplicated += 1
            print(f"   [dup]  {ref.name} → двойник ID {twin.id}")
        else:
            s3_key = await s3.upload_bytes(blob, remote_key, mime_for(ref.name))
            if not s3_key:
                stats.errors += 1
                print(f"   [err]  не выгрузилось в S3: {ref.name}")
                return
            tmp_dir = Path(tempfile.mkdtemp(prefix="wayback_html_"))
            tmp_path = tmp_dir / f"{sha256[:12]}.{ext or 'bin'}"
            tmp_path.write_bytes(blob)
            try:
                variants, duration = await generate_and_upload(
                    s3,
                    base_key=f"board_{board.id}/thread_{thread_num}/{sha256[:12]}",
                    media_type=media_type,
                    local_path=tmp_path,
                    file_data=blob if media_type == "image" else None,
                    video_web=video_web,
                )
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

            await repo.create(
                board_id=board.id,
                thread_id=thread_num,
                source_id=board.source_id,
                original_name=ref.name,
                source_url=thread_url,
                source_md5=md5,
                file_hash=sha256,
                file_size=size,
                mime_type=mime_for(ref.name),
                media_type=media_type,
                width=ref.width,
                height=ref.height,
                s3_bucket=settings.storage_bucket,
                s3_key=s3_key,
                variants=variants,
                duration_seconds=duration,
                download_status="done",
                is_visible=visible,
                is_active=True,
                is_premium=premium,
            )
            stats.created += 1
            print(f"   [ok]   {ref.name} ({size // 1024} КБ, тред {thread_num})")


async def run(args: argparse.Namespace) -> Stats:
    """Проходит треды раздела: страницы читает из архива, файлы — по ссылкам."""
    stats = Stats()
    s3 = S3Storage()
    if not s3.is_configured:
        print("[err] S3 не настроен — импорт невозможен")
        return stats

    refs = cdx_threads(args.board, args.host, delay=args.delay, from_year=args.from_year)
    # Лимит применяем после фильтра по годам: в CDX он режет выборку до отсева
    if args.threads_limit:
        refs = refs[: args.threads_limit]
    print(f"[cdx]  HTML-страниц тредов в архиве: {len(refs)}")
    if not refs:
        return stats

    async with async_session_factory() as session:
        source = await ensure_source(session, args.source, "Веб-архив", f"https://{args.host}")
        board = await ensure_board(
            session,
            args.board,
            args.title or args.board.upper(),
            source,
            visible=not args.hidden,
            premium=args.premium,
        )
        await session.commit()
        repo = MediaRepository(session)

        for ref in refs:
            stats.threads_seen += 1
            page = fetch(f"{ARCHIVE}/{ref.timestamp}id_/{ref.url}", delay=args.delay)
            if not page:
                stats.errors += 1
                print(f"[miss] страница треда /{args.board}/res/{ref.num}.html")
                continue

            parsed = parse_thread_page(page.decode("utf-8", errors="ignore"), ref.num)
            print(
                f"[thread] /{args.board}/{ref.num}: «{parsed.subject or '—'}», "
                f"постов {parsed.posts_count}, файлов {len(parsed.files)}"
            )
            if args.files_limit:
                parsed.files = parsed.files[: args.files_limit]
            stats.files_seen += len(parsed.files)

            if not args.dry_run:
                thread = await ensure_thread(session, board, ref.num, None, not args.hidden)
                if parsed.subject:
                    thread.subject = parsed.subject
                if parsed.posts_count:
                    thread.posts_count = parsed.posts_count
                if parsed.posted_at:
                    thread.thread_timestamp = parsed.posted_at
                thread.files_detected = len(parsed.files)
                await session.flush()

            for index, file_ref in enumerate(parsed.files, start=1):
                try:
                    await import_file(
                        session,
                        s3,
                        repo,
                        board,
                        ref.num,
                        file_ref,
                        ref.url,
                        visible=not args.hidden,
                        premium=args.premium,
                        video_web=not args.no_video_transcode,
                        year=ref.timestamp[:4] or None,
                        delay=args.delay,
                        dry_run=args.dry_run,
                        stats=stats,
                    )
                except Exception as exc:  # noqa: BLE001
                    stats.errors += 1
                    print(f"   [err]  {file_ref.name}: {exc}")
                # Коммит пачками: падение посреди треда не теряет уже залитое
                if not args.dry_run and index % args.commit_every == 0:
                    await session.commit()

            if not args.dry_run:
                await session.commit()

    return stats


def build_parser() -> argparse.ArgumentParser:
    """Аргументы запуска: что импортируем и насколько осторожно."""
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.wayback_html_import",
        description="Импорт раздела 2ch из HTML-снапшотов веб-архива (без JSON-каталога).",
    )
    parser.add_argument("--board", default="h", help="слаг раздела-источника (по умолчанию h)")
    parser.add_argument("--title", default="", help="название раздела на сайте")
    parser.add_argument("--source", default="wayback", help="код источника-архива в БД")
    parser.add_argument("--host", default="2ch.hk", help="хост, у которого берём снапшоты")
    parser.add_argument(
        "--threads-limit", type=int, default=0, help="сколько тредов обработать (0 — все)"
    )
    parser.add_argument(
        "--from-year",
        default="2013",
        help="брать страницы начиная с этого года (у ранних снапшотов файлов в архиве нет)",
    )
    parser.add_argument("--files-limit", type=int, default=0, help="файлов в треде (0 — все)")
    parser.add_argument("--delay", type=float, default=1.5, help="пауза между запросами, с")
    parser.add_argument("--commit-every", type=int, default=5, help="коммит каждые N файлов")
    parser.add_argument("--hidden", action="store_true", help="не показывать раздел публично")
    parser.add_argument("--premium", action="store_true", help="файлы раздела — по подписке")
    parser.add_argument(
        "--no-video-transcode",
        action="store_true",
        help="не перекодировать видео в 720p (быстрее: архивные ролики длинные)",
    )
    parser.add_argument("--dry-run", action="store_true", help="скачать и посчитать, не записывая")
    return parser


def print_report(stats: Stats, args: argparse.Namespace) -> None:
    """Итог прогона — по нему видно, что и сколько залилось."""
    print("\n" + "=" * 62)
    print(f"ИТОГ импорта HTML /{args.board} ({'dry-run' if args.dry_run else 'боевой прогон'})")
    print(f"  тредов просмотрено : {stats.threads_seen}")
    print(f"  файлов в разметке  : {stats.files_seen}")
    print(f"  скачано из архива  : {stats.downloaded} (~{stats.bytes_saved / 1_048_576:.1f} МБ)")
    print(f"  создано записей    : {stats.created}")
    print(f"  дублей по SHA-256  : {stats.duplicated}")
    print(f"  пропущено (уже есть): {stats.skipped}")
    print(f"  нет в архиве       : {stats.missing}")
    print(f"  ошибок             : {stats.errors}")
    print("=" * 62)


def main(argv: Optional[List[str]] = None) -> int:
    """Точка входа: `python -m src.tools.wayback_html_import --board h --dry-run`."""
    args = build_parser().parse_args(argv)
    try:
        stats = asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n[warn] прервано — уже залитые файлы остались в S3 и БД")
        return 130
    print_report(stats, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())


