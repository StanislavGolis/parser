# src/parsers/wayback.py
"""Адаптер архивного источника: разделы 2ch, вытащенные из Wayback Machine.

Живьём часть разделов недоступна (движок отдаёт 500), но их каталог и медиа
сохранились в веб-архиве. Благодаря этому адаптеру архив ведёт себя как обычный
источник в центре управления: «Разделы сайта» → «Добавить» → «Загрузить записи»
(треды встают в очередь) → включённым тредам конвейер скачивает файлы.

Файлы берутся снапшотами архива (`/<timestamp>im_/<url>`), поэтому в очередь
попадают все свободные треды архива, а не только те, что уже разобрал разовый
массовый импорт (`src/tools/wayback_import.py`). Архивный слой (CDX, снапшоты,
разбор `catalog.json`) общий с импортёром и живёт в `src/tools/wayback_import.py`.
"""
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from src.parsers.base import BoardNode, CatalogResult, FileNode, ThreadNode
from src.tools.wayback_import import (
    ARCHIVE_WEB,
    VIDEO_EXTS,
    cdx_snapshots,
    fetch_catalog,
    mime_for,
)

# Разделы, которые забираем из архива. Список расширяется в админке через
# `sources.config["boards"]` — тогда разделы появятся в «Разделах сайта».
DEFAULT_BOARDS = ["e"]


class WaybackAdapter:
    """Источник «архив Wayback Machine»: каталог и файлы разделов из веб-архива."""

    code = "wayback"
    BASE_URL = "https://web.archive.org"

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        boards: Optional[List[str]] = None,          # разделы из `sources.config["boards"]`
        media_host: str = "2ch.su",                 # где лежат медиафайлы (2ch.su — без Cloudflare)
        catalog_hosts: Optional[List[str]] = None,  # где искать архивный catalog.json
        delay: float = 1.0,                         # пауза между запросами к архиву
        max_files: int = 20000,                     # лимит снапшотов файлов на раздел
        **_options,
    ):
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.media_host = media_host
        self.catalog_hosts = list(catalog_hosts or ["2ch.hk", "2ch.su", "2ch.life"])
        self.delay = float(delay or 0)
        self.max_files = int(max_files or 0)
        # Список разделов приходит из конфига источника (`sources.config["boards"]`):
        # так новый раздел архива добавляется без правок кода.
        self.boards = [str(board).strip() for board in (boards or []) if str(board).strip()]
        # Архив отвечает медленно и лимитирует: каталог и список снапшотов держим
        # в памяти процесса — иначе админка дёргала бы архив на каждый запрос.
        self._catalog: Dict[str, Dict] = {}
        self._catalog_snapshot: Dict[str, Optional[str]] = {}
        self._snapshots: Dict[str, list] = {}

    @property
    def default_boards(self) -> List[str]:
        """Разделы для «Разделов сайта»: из конфига источника либо базовый список."""
        return list(self.boards) or list(DEFAULT_BOARDS)

    async def __aenter__(self) -> "WaybackAdapter":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    def download_headers(self) -> Dict[str, str]:
        """Архив отдаёт файлы без Referer — дополнительных заголовков не нужно."""
        return {}

    # ───────────────────────── Разделы ─────────────────────────

    async def fetch_boards(self) -> Optional[List[BoardNode]]:
        """Разделы архива — для «Разделов сайта» в центре управления.

        `hint` — сколько тредов сохранилось в архивном каталоге (оценка объёма).
        `None` — каталог не пришёл (архив не ответил): админка покажет это честно,
        а не пустой список.
        """
        items: List[BoardNode] = []
        any_ok = False
        for slug in self.default_boards:
            threads, snapshot = await self._load_catalog(slug)
            if snapshot:
                any_ok = True
            items.append(
                BoardNode(
                    slug=slug,
                    title=f"/{slug}",
                    group="разделы",
                    hint=len(threads),
                )
            )
        return items if any_ok else None

    # ───────────────────────── Каталог ─────────────────────────

    async def _load_catalog(self, board_slug: str) -> tuple[Dict, Optional[str]]:
        """Архивный каталог раздела (кэш на процесс): треды + время снапшота."""
        if board_slug not in self._catalog:
            threads, snapshot = await asyncio.to_thread(
                fetch_catalog, board_slug, self.catalog_hosts, self.delay
            )
            self._catalog[board_slug] = threads
            self._catalog_snapshot[board_slug] = snapshot
        return self._catalog[board_slug], self._catalog_snapshot.get(board_slug)

    async def fetch_catalog(self, board_slug: str) -> Optional[CatalogResult]:
        """Каталог раздела: все треды архива — их админка ставит в очередь.

        `fingerprint` — первый файл треда: для архива это метка состояния (новые
        файлы там не появляются, но планировщику нужен ориентир).
        """
        threads, snapshot = await self._load_catalog(board_slug)
        if not snapshot and not threads:
            return None
        items: List[ThreadNode] = []
        for num, thread in threads.items():
            items.append(
                ThreadNode(
                    external_id=str(num),
                    subject=thread.subject,
                    posts_count=thread.posts_count,
                    files_count=len(thread.files),
                    views_count=thread.views_count,
                    fingerprint=(thread.files[0].name if thread.files else None),
                )
            )
        return CatalogResult(
            threads=items,
            title=f"/{board_slug}",
            description=None,
        )

    # ───────────────────────── Файлы треда ─────────────────────────

    async def _load_snapshots(self, board_slug: str) -> list:
        """Все снапшоты файлов раздела (кэш): CDX отвечает медленно."""
        if board_slug not in self._snapshots:
            self._snapshots[board_slug] = await asyncio.to_thread(
                cdx_snapshots,
                self.media_host,
                "src/*",
                board_slug,
                self.max_files,
                self.delay,
            )
        return self._snapshots[board_slug]

    async def fetch_thread_files(
        self, board_slug: str, external_id: str
    ) -> Optional[List[FileNode]]:
        """Файлы треда архива: снапшоты `/src/<thread>/<файл>`.

        `source_url` — адрес снапшота (`im_` — оригинальные байты), поэтому
        конвейер скачивает файл как обычно. Размер, размеры кадра и md5 берём из
        архивного каталога, если он их сохранил.

        `None` — список снапшотов не получен (архив не ответил): тред останется
        в очереди, планировщик вернётся к нему позже.
        """
        snapshots = await self._load_snapshots(board_slug)
        if not snapshots:
            return None

        marker = f"/src/{external_id}/"
        threads, _ = await self._load_catalog(board_slug)
        meta = threads.get(str(external_id))
        by_name = {f.name: f for f in (meta.files if meta else [])}

        nodes: List[FileNode] = []
        position = 0
        for snapshot in snapshots:
            path = snapshot.url.split("://", 1)[-1]
            if marker not in path:
                continue
            name = path.rsplit("/", 1)[-1]
            if not name:
                continue
            position += 1
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            catalog_file = by_name.get(name)
            nodes.append(
                FileNode(
                    filename=name,
                    original_name=name,
                    source_url=f"{ARCHIVE_WEB}/{snapshot.timestamp}im_/{snapshot.url}",
                    media_type="video" if ext in VIDEO_EXTS else "image",
                    mime_type=mime_for(name),
                    size_bytes=(catalog_file.size if catalog_file else 0),
                    md5=(catalog_file.md5 if catalog_file else None),
                    width=(catalog_file.width if catalog_file else None),
                    height=(catalog_file.height if catalog_file else None),
                    post_num=(catalog_file.order if catalog_file else position),
                )
            )
        return nodes


__all__ = ["WaybackAdapter", "DEFAULT_BOARDS"]


