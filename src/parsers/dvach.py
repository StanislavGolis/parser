# src/parsers/dvach.py
"""Адаптер источника 2ch.hk (JSON API).

Источник-специфичное здесь и только оно:

- `catalog.json` доски → «треды» (`ThreadNode`): тема, комментарий ОП, дата,
  счётчики постов/файлов (нужны планировщику, чтобы понимать, появились ли новые
  файлы, без обхода треда) и просмотры;
- `res/{id}.json` → файлы треда (`FileNode`) с md5, размером и разрешением **до**
  скачивания — поэтому дедупликация выполняется до загрузки файла.

Всё остальное — общее и живёт отдельно: план обхода и очередь
(`services/scan_planner.py`), скачивание/валидация/S3/деривативы/БД
(`services/pipeline.py`), реестр источников и флаги прогонов
(`services/sources.py`). Контракт адаптера — `src/parsers/base.py`.
"""
import re
import time
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp

from src.parsers.base import BoardNode, CatalogResult, FileNode, ThreadNode
from src.services.media_validator import MediaValidator

# Кэш списка досок форума: index.json статичен, а вкладка «Доски форума»
# опрашивает его при каждом открытии
BOARDS_CACHE_TTL = 300
_BOARDS_CACHE: Dict[str, object] = {}

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


class DvachAdapter:
    """Парсер 2ch.hk на JSON API (реализация `SourceAdapter`)."""

    code = "dvach"
    BASE_URL = "https://2ch.hk"

    def __init__(self, base_url: Optional[str] = None, **_options):
        # base_url переопределяется зеркалом/тестами; остальные опции источника
        # (лимиты, задержки) применяются в планировщике и конвейере.
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.http_session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "DvachAdapter":
        self.http_session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.http_session:
            await self.http_session.close()

    def download_headers(self) -> Dict[str, str]:
        """2ch отдаёт файлы без Referer — дополнительных заголовков не нужно."""
        return {}

    @property
    def default_boards(self) -> List[str]:
        """2ch не диктует список разделов: их выбирает админ из index.json."""
        return []

    async def fetch_boards(self) -> Optional[List[BoardNode]]:
        """Доски форума из `index.json` (аналог вкладки «Доски форума»).

        Список кэшируется на 5 минут: админка может дёргать его при каждом
        открытии вкладки, а index.json — статичный и тяжёлый.
        """
        now = time.time()
        cached = _BOARDS_CACHE.get("items")
        if cached is not None and now - float(_BOARDS_CACHE.get("ts", 0)) < BOARDS_CACHE_TTL:
            return cached  # type: ignore[return-value]

        data = await self._get_json(f"{self.base_url}/index.json")
        if data is None:
            return None

        items = [
            BoardNode(
                slug=str(board["id"]),
                title=(board.get("name") or None),
                group=(board.get("category") or None),
                hint=int(board.get("threads") or 0),
            )
            for board in (data.get("boards") or [])
            if board.get("id")
        ]
        _BOARDS_CACHE["items"] = items
        _BOARDS_CACHE["ts"] = now
        return items

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
        except Exception as e:  # noqa: BLE001
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

    @staticmethod
    def _clean_comment(html: Optional[str]) -> Optional[str]:
        """Переводит HTML-комментарий ОП в короткий plaintext для хранения."""
        if not html:
            return None
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:400] or None

    # ─────────────────────── Каталог доски ───────────────────────

    @staticmethod
    def _thread_node(t: dict) -> Optional[ThreadNode]:
        """Элемент каталога → «тред» источника."""
        num = t.get("num")
        if not num:
            return None
        ts = t.get("timestamp")
        return ThreadNode(
            external_id=str(int(num)),
            subject=(t.get("subject") or "").strip()[:500] or None,
            comment=DvachAdapter._clean_comment(t.get("comment")),
            timestamp=datetime.fromtimestamp(int(ts)) if ts else None,
            posts_count=int(t.get("posts_count") or 0),
            files_count=int(t.get("files_count") or 0),
            views_count=int(t.get("views") or 0),
        )

    async def fetch_catalog(self, board_slug: str) -> Optional[CatalogResult]:
        """Каталог доски: метаданные раздела + список тредов.

        `None` — каталог не прочитался (сеть/ошибка 2ch: раздел мог быть удалён).
        """
        data = await self._get_json(f"{self.base_url}/{board_slug}/catalog.json")
        if not data:
            return None
        info = data.get("board") or {}
        nodes = [
            node for node in (self._thread_node(t) for t in data.get("threads") or []) if node
        ]
        return CatalogResult(
            threads=nodes,
            title=info.get("name"),
            description=info.get("info_outer"),
        )

    # ──────────────────────── Файлы треда ────────────────────────

    def _file_meta(self, file: dict, post_num: int = 0) -> Optional[FileNode]:
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
        return FileNode(
            filename=filename,
            original_name=file.get("displayname") or filename,
            source_url=f"{self.base_url}{path}",
            media_type=media_type,
            mime_type=MIME_BY_EXT.get(ext, "application/octet-stream"),
            size_bytes=int(file.get("size") or 0) * 1024,
            md5=md5,
            width=file.get("width"),
            height=file.get("height"),
            post_num=post_num,
        )

    async def fetch_thread_files(
        self, board_slug: str, external_id: str
    ) -> Optional[List[FileNode]]:
        """Файлы треда (без скачивания).

        `None` — не удалось прочитать `res/{id}.json` (сеть/ошибка): планировщик
        оставит тред в очереди, а не посчитает его просканированным. Пустой
        список — в треде действительно нет «наших» файлов.
        """
        url = f"{self.base_url}/{board_slug}/res/{external_id}.json"
        data = await self._get_json(url)
        if data is None:
            return None

        files: List[FileNode] = []
        for post in self._extract_posts(data):
            post_num = int(post.get("num") or 0)
            for raw in post.get("files") or []:
                # Номер поста нужен для инкрементального прохода: частые сканы
                # смотрят только посты новее `last_post_num`.
                node = self._file_meta(raw, post_num=post_num)
                if node:
                    files.append(node)
        return files

