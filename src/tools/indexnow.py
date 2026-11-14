# src/tools/indexnow.py
"""Уведомление поисковиков (IndexNow) о новых страницах архива.

IndexNow — единственный быстрый канал: Bing и Яндекс принимают список адресов и
ставят их в очередь обхода за минуты. Google sitemap-ping не поддерживает с 2023
года — карты он забирает по своему расписанию, ссылка на них есть в robots.txt.

Что отправляем: страницы файлов и их треды, появившиеся за последние часы.
Запуск по расписанию (cron) — см. DEPLOY.md.

    python -m src.tools.indexnow --hours 2 --dry-run
    python -m src.tools.indexnow --hours 2
"""
import argparse
import asyncio
from datetime import datetime, timedelta
from typing import Iterable, List, Tuple

import httpx
from sqlalchemy import select

from src.core.config import settings
from src.core.db import async_session_factory
from src.core.models import Board, Media

# Предел протокола: 10 000 адресов за один запрос
BATCH_SIZE = 10000
# Endpoint IndexNow: раздаёт уведомления участникам (Bing, Яндекс и др.)
ENDPOINT = "https://api.indexnow.org/indexnow"


def _site_url() -> str:
    """Публичный адрес сайта: берём из настроек, иначе — прод-домен."""
    base = (settings.PUBLIC_BASE_URL or settings.SITE_URL or "https://media-archive.example").strip()
    return base.rstrip("/")


async def collect(hours: int) -> Tuple[List[str], int]:
    """Адреса новых файлов и их тредов за период. Возвращает (urls, файлов)."""
    since = datetime.utcnow() - timedelta(hours=hours)
    base = _site_url()

    async with async_session_factory() as session:
        # Видимые файлы за период: из них берём адреса страниц файлов
        rows = (
            await session.execute(
                select(Media.id)
                .join(Board, Board.id == Media.board_id)
                .where(
                    Media.created_at >= since,
                    Media.is_active.is_(True),
                    Media.is_visible.is_(True),
                    Media.duplicate_of_id.is_(None),
                    Board.is_visible.is_(True),
                )
                .order_by(Media.id.desc())
            )
        ).all()
        if not rows:
            return [], 0

        # Треды этих файлов: страница треда обновилась → её тоже стоит переобойти
        thread_rows = (
            await session.execute(
                select(Media.thread_id)
                .join(Board, Board.id == Media.board_id)
                .where(
                    Media.created_at >= since,
                    Media.is_active.is_(True),
                    Media.is_visible.is_(True),
                    Media.duplicate_of_id.is_(None),
                    Board.is_visible.is_(True),
                )
                .distinct()
            )
        ).all()

    urls: List[str] = [f"{base}/t/{int(value)}" for (value,) in thread_rows]
    urls += [f"{base}/media/{int(row[0])}" for row in rows]
    return urls, len(rows)


async def send(urls: Iterable[str], key: str, key_location: str, host: str) -> int:
    """Отправляет адреса батчами. Возвращает число отправленных адресов."""
    payload_urls = list(urls)
    sent = 0
    async with httpx.AsyncClient(timeout=30) as client:
        for start in range(0, len(payload_urls), BATCH_SIZE):
            chunk = payload_urls[start : start + BATCH_SIZE]
            try:
                response = await client.post(
                    ENDPOINT,
                    json={
                        "host": host,
                        "key": key,
                        "keyLocation": key_location,
                        "urlList": chunk,
                    },
                    headers={"content-type": "application/json; charset=utf-8"},
                )
            except Exception as exc:  # сеть/таймаут — следующий прогон догонит
                print(f"   [err]  IndexNow недоступен: {exc}")
                break
            # 200/202 — принято; 422 — некорректные адреса; 403 — ключ не подтверждён
            print(f"   [sent] {len(chunk)} адресов → HTTP {response.status_code}")
            if response.status_code not in (200, 202):
                print(f"          ответ: {response.text[:200]}")
            sent += len(chunk)
    return sent


async def main() -> None:
    parser = argparse.ArgumentParser(description="IndexNow: уведомить поисковики о новых страницах")
    parser.add_argument("--hours", type=int, default=2, help="за сколько часов брать новые файлы")
    parser.add_argument("--dry-run", action="store_true", help="только показать адреса")
    args = parser.parse_args()

    base = _site_url()
    key = (settings.INDEXNOW_KEY or "").strip()
    host = base.split("://", 1)[-1]

    urls, files = await collect(args.hours)
    print(f"=== новых файлов за {args.hours} ч: {files}; адресов к уведомлению: {len(urls)}")
    if args.dry_run:
        for url in urls[:20]:
            print(f"   {url}")
        return
    if not urls:
        print("   (нечего отправлять)")
        return
    if not key:
        print("   [warn] INDEXNOW_KEY не задан — уведомление пропущено")
        return

    sent = await send(urls, key, f"{base}/indexnow-key.txt", host)
    print(f"=== отправлено адресов: {sent}")


if __name__ == "__main__":
    asyncio.run(main())
