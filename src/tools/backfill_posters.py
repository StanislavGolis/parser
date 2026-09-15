# src/tools/backfill_posters.py
"""Постеры для файлов, у которых превью нет (без транскода видео).

Зачем отдельный инструмент. Основной бэкфилл (`POST /admin/backfill-variants`)
пересобирает и полную версию файла: для видео это 720p-транскод, который идёт
минутами и грузит диск. Когда не хватает **только превью** (файл скачан до
появления деривативов, сбой ffmpeg, транскод был выключен), достаточно постера:
карточка в лентах перестаёт показывать заглушку «недоступно», а премиум-раздел
получает размытый вариант.

Как устроено: берём `media.s3_key`, скачиваем оригинал во временный файл и
вызываем общий `generate_and_upload` с `video_web=False` — для видео строятся
постер (`thumb`) и размытый постер (`thumb_blur`), полная версия не трогается.

Пример запуска (внутри контейнера api, где есть ffmpeg и доступ к S3):

    python -m src.tools.backfill_posters --visible-only --dry-run
    python -m src.tools.backfill_posters --visible-only      # боевой прогон
    python -m src.tools.backfill_posters --ids 26094,26100

Ключи:
    --visible-only  только файлы, видимые на сайте (как в лентах)
    --limit N       максимум файлов за прогон (0 — без ограничения)
    --ids a,b,c     конкретные файлы вместо автоматического отбора
    --dry-run       показать список и выйти

Дубликаты (`duplicate_of_id`) пропускаются: на сайте они не показываются.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tempfile
from pathlib import Path

from sqlalchemy import or_, select

from src.core.db import async_session_factory
from src.core.models import Media
from src.services.derivatives import generate_and_upload
from src.services.s3_storage import S3Storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill_posters")


def _missing_preview_clause():
    """«Файл лежит в S3, но превью-дериватива нет» — кого чинит инструмент.

    Дубликаты не трогаем: на сайте они не показываются (`duplicate_of_id`), им
    превью не нужно — иначе в работу попадала бы тысяча лишних файлов.
    """
    return (
        Media.s3_key.isnot(None),
        Media.duplicate_of_id.is_(None),
        or_(Media.variants.is_(None), Media.variants["thumb"].is_(None)),
    )


async def _run(args: argparse.Namespace) -> int:
    s3 = S3Storage()
    if not s3.is_configured:
        log.error("S3 не настроен: проверьте S3_* в .env")
        return 1

    async with async_session_factory() as session:
        query = select(Media).where(*_missing_preview_clause())
        if args.visible_only:
            query = query.where(Media.is_visible.is_(True), Media.is_active.is_(True))
        if args.ids:
            query = query.where(Media.id.in_(args.ids))
        query = query.order_by(Media.id)
        if args.limit:
            query = query.limit(args.limit)

        items = (await session.execute(query)).scalars().all()
        log.info("файлов без превью: %s", len(items))
        if not items:
            return 0
        if args.dry_run:
            for m in items:
                log.info("  id=%s %s board=%s %s", m.id, m.media_type, m.board_id, m.s3_key)
            return 0

        fixed = failed = 0
        with tempfile.TemporaryDirectory() as tmp:
            for m in items:
                orig = Path(tmp) / f"orig_{m.id}"
                try:
                    if not await s3.download_to_file(m.s3_key, orig):
                        log.warning("id=%s: не удалось скачать %s", m.id, m.s3_key)
                        failed += 1
                        continue
                    prefix = (m.file_hash or "")[:12] or str(m.id)
                    base = f"board_{m.board_id}/thread_{m.thread_id}/{prefix}"
                    variants, duration = await generate_and_upload(
                        s3,
                        base_key=base,
                        media_type=m.media_type,
                        local_path=orig,
                        # Полную версию не пересобираем — нужен только постер/превью
                        video_web=False,
                    )
                    if variants and variants.get("thumb"):
                        # Дополняем, а не перезаписываем: прежние варианты (например,
                        # уже готовый `video`) остаются на месте
                        m.variants = {**(m.variants or {}), **variants}
                        if duration:
                            m.duration_seconds = duration
                        await session.commit()
                        fixed += 1
                        log.info("id=%s: превью готово (%s)", m.id, ", ".join(sorted(variants)))
                    else:
                        log.warning("id=%s: постер не построился", m.id)
                        failed += 1
                except Exception as exc:  # noqa: BLE001
                    log.warning("id=%s: ошибка — %s", m.id, exc)
                    failed += 1
                finally:
                    orig.unlink(missing_ok=True)

    log.info("готово: исправлено %s, ошибок %s", fixed, failed)
    return 0 if failed == 0 else 2


def _ids(value: str):
    return [int(part) for part in value.replace(" ", "").split(",") if part]


def main() -> None:
    parser = argparse.ArgumentParser(description="Постеры для файлов без превью")
    parser.add_argument("--visible-only", action="store_true", help="только видимые файлы")
    parser.add_argument("--limit", type=int, default=0, help="максимум файлов (0 — все)")
    parser.add_argument("--ids", type=_ids, help="список id через запятую")
    parser.add_argument("--dry-run", action="store_true", help="только показать список")
    sys.exit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
