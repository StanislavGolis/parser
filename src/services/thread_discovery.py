# src/services/thread_discovery.py
"""Сканирование каталога доски: создание/обновление тредов без скачивания файлов.

Нужно для кнопки «Загрузить треды» в админке: список тредов появляется до
первого полного прохода парсера. Прогресс складывается в Redis.
"""
import re
from datetime import datetime
from typing import Awaitable, Callable, List, Optional

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import Board, ThreadState
from src.repositories.thread_state_repo import ThreadStateRepository

BASE_URL = "https://2ch.hk"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def scan_key(slug: str) -> str:
    """Ключ прогресса сканирования доски в Redis."""
    return f"scan:board:{slug}"


class ThreadDiscovery:
    """Только обнаружение тредов доски (без выгрузки файлов)."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ThreadStateRepository(session)

    @staticmethod
    def _clean_comment(html: Optional[str]) -> Optional[str]:
        if not html:
            return None
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:400] or None

    async def fetch_catalog(self, slug: str) -> List[dict]:
        url = f"{BASE_URL}/{slug}/catalog.json"
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession() as http:
            async with http.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT}) as resp:
                resp.raise_for_status()
                data = await resp.json()
        return (data or {}).get("threads") or []

    async def discover(
        self,
        board: Board,
        on_progress: Optional[Callable[[int, int], Awaitable[None]]] = None,
    ) -> dict:
        """Обходит каталог доски и заводит/обновляет threads_state.

        Счётчики (posts_count/files_count) у новых тредов НЕ заполняются:
        так парсер увидит «изменение» и скачает файлы при следующем проходе.
        """
        threads = [t for t in await self.fetch_catalog(board.slug) if t.get("num")]
        total = len(threads)
        created = updated = 0

        if on_progress:
            await on_progress(0, total)

        for i, t in enumerate(threads, start=1):
            thread_id = int(t["num"])
            subject = (t.get("subject") or "").strip()[:500] or None
            comment = self._clean_comment(t.get("comment"))
            ts = t.get("timestamp")
            thread_ts = datetime.fromtimestamp(int(ts)) if ts else None
            posts_count = int(t.get("posts_count") or 0)
            files_count = int(t.get("files_count") or 0)
            views_count = int(t.get("views") or 0)

            state = await self.repo.get_by_board_thread(board.id, thread_id)
            if state is None:
                state = ThreadState(
                    board_id=board.id,
                    thread_id=thread_id,
                    is_active=True,
                    parse_enabled=(board.parse_mode == "all"),
                    subject=subject,
                    comment=comment,
                    thread_timestamp=thread_ts,
                    posts_count=posts_count,
                    files_count=files_count,
                    views_count=views_count,
                )
                self.session.add(state)
                created += 1
            else:
                state.is_active = True
                if subject:
                    state.subject = subject
                if comment:
                    state.comment = comment
                if thread_ts:
                    state.thread_timestamp = thread_ts
                state.posts_count = posts_count
                state.files_count = files_count
                state.views_count = views_count
                updated += 1

            # Периодически коммитим и обновляем прогресс
            if i % 25 == 0:
                await self.session.commit()
                if on_progress:
                    await on_progress(i, total)

        await self.session.commit()
        if on_progress:
            await on_progress(total, total)
        return {"total": total, "created": created, "updated": updated}
