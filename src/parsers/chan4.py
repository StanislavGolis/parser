# src/parsers/chan4.py
"""Адаптер источника 4chan (официальный JSON API).

Источник-специфичное здесь и только оно:

- `boards.json` → список разделов для вкладки «Разделы сайта» (77 живых досок);
- `{board}/catalog.json` → «треды» (`ThreadNode`): тема, комментарий ОП, дата,
  счётчики ответов/файлов и `last_modified` как метка изменения — планировщику
  этого хватает, чтобы понять, появились ли новые файлы, без обхода треда;
- `{board}/thread/{no}.json` → файлы треда (`FileNode`) с md5 (base64 → hex),
  размером и разрешением **до** скачивания, поэтому дедупликация идёт до загрузки;
- медиа лежит на `i.4cdn.org` и отдаётся без Referer/UA.

Особенность 4chan: треды живут недолго (собственный архив — несколько суток),
поэтому источник надо опрашивать часто (`PARSE_INTERVAL` ~5 минут): что успели
скачать — остаётся у нас, остальное добирается из сторонних архивов отдельным
инструментом (`src/tools/chan4_import.py`).

Всё остальное — общее: план обхода и очередь (`services/scan_planner.py`),
скачивание/валидация/S3/деривативы/БД (`services/pipeline.py`), реестр
источников (`services/sources.py`). Контракт адаптера — `src/parsers/base.py`.
"""
import base64
import re
import time
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp

from src.parsers.base import BoardNode, CatalogResult, FileNode, ThreadNode
from src.services.media_validator import MediaValidator

# Кэш списка досок: boards.json статичен, а вкладка «Разделы сайта» опрашивает
# его при каждом открытии. Он же хранит названия/описания разделов для каталога.
BOARDS_CACHE_TTL = 300
_BOARDS_CACHE: Dict[str, object] = {}

# Медиа 4chan отдаётся по `tim` (Unix-время загрузки с микросекундами) + ext
MEDIA_BASE = "https://i.4cdn.org"

MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "webm": "video/webm",
}


class Chan4Adapter:
    """Парсер 4chan на официальном JSON API (реализация `SourceAdapter`)."""

    code = "chan4"
    BASE_URL = "https://a.4cdn.org"
    # Разделы, которые предлагаются в конфиге при первом запуске источника
    DEFAULT_BOARDS = ["s"]

    def __init__(
        self,
        base_url: Optional[str] = None,
        boards: Optional[List[str]] = None,
        **_options,
    ):
        # base_url переопределяется зеркалом/тестами; остальные опции источника
        # (лимиты, задержки) применяются в планировщике и конвейере.
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.configured_boards = [str(b).strip("/") for b in (boards or []) if b]
        self.http_session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "Chan4Adapter":
        self.http_session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.http_session:
            await self.http_session.close()

    def download_headers(self) -> Dict[str, str]:
        """i.4cdn.org отдаёт файлы без Referer — дополнительных заголовков нет."""
        return {}

    @property
    def default_boards(self) -> List[str]:
        """Разделы из конфига источника (`sources.config["boards"]`)."""
        return list(self.configured_boards) or list(self.DEFAULT_BOARDS)

    # ───────────────────────── HTTP / JSON ─────────────────────────

    async def _get_json(self, url: str) -> Optional[object]:
        """GET JSON. `None` — сеть/HTTP-ошибка: вызывающий решает, что делать."""
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
                )
            }
            async with self.http_session.get(url, timeout=timeout, headers=headers) as response:
                response.raise_for_status()
                return await response.json(content_type=None)
        except Exception as e:  # noqa: BLE001
            print(f"   [err] HTTP {url}: {e}")
            return None

    @staticmethod
    def _clean_comment(html: Optional[str]) -> Optional[str]:
        """HTML-комментарий ОП → короткий plaintext для хранения в БД."""
        if not html:
            return None
        text = re.sub(r"<br\s*/?>", " ", html, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = (
            text.replace("&quot;", '"')
            .replace("&#039;", "'")
            .replace("&gt;", ">")
            .replace("&lt;", "<")
            .replace("&amp;", "&")
        )
        text = re.sub(r"\s+", " ", text).strip()
        return text[:400] or None

    @staticmethod
    def _md5_hex(md5_b64: Optional[str]) -> Optional[str]:
        """md5 в API 4chan — base64; в БД и дедупе нужен hex.

        Если строка не декодируется — вернём `None`: конвейер посчитает
        синтетический `md5(url)`, а точную проверку сделает SHA-256 после скачивания.
        """
        if not md5_b64:
            return None
        try:
            return base64.b64decode(md5_b64).hex()
        except Exception:  # noqa: BLE001
            return None

    # ───────────────────────────── Разделы ─────────────────────────────

    async def _boards_meta(self) -> Optional[Dict[str, dict]]:
        """`boards.json` → {слаг: раздел} с кэшем на 5 минут."""
        now = time.time()
        cached = _BOARDS_CACHE.get("meta")
        if cached is not None and now - float(_BOARDS_CACHE.get("ts", 0)) < BOARDS_CACHE_TTL:
            return cached  # type: ignore[return-value]

        data = await self._get_json(f"{self.base_url}/boards.json")
        if not isinstance(data, dict):
            return None

        meta: Dict[str, dict] = {}
        items: List[BoardNode] = []
        for board in data.get("boards") or []:
            slug = str(board.get("board") or "").strip()
            if not slug:
                continue
            meta[slug] = board
            items.append(
                BoardNode(
                    slug=slug,
                    title=(board.get("title") or None),
                    # У 4chan нет категорий разделов, зато есть метка «безопасный»
                    # (`ws_board=1` — SFW), по ней и группируем список в админке
                    group="SFW" if board.get("ws_board") else "NSFW",
                    hint=int(board.get("per_page") or 0) * int(board.get("pages") or 0),
                )
            )
        _BOARDS_CACHE["meta"] = meta
        _BOARDS_CACHE["items"] = items
        _BOARDS_CACHE["ts"] = now
        return meta

    async def fetch_boards(self) -> Optional[List[BoardNode]]:
        """Разделы 4chan для выбора в админке (аналог «Досок форума»)."""
        await self._boards_meta()
        items = _BOARDS_CACHE.get("items")
        return items  # type: ignore[return-value]

    async def _board_meta(self, board_slug: str) -> dict:
        """Метаданные одного раздела (title/description для карточки доски)."""
        meta = await self._boards_meta() or {}
        return meta.get(board_slug) or {}

    # ─────────────────────────── Каталог доски ───────────────────────────

    @staticmethod
    def _thread_node(t: dict) -> Optional[ThreadNode]:
        """Элемент каталога → «тред» источника."""
        num = t.get("no")
        if not num:
            return None
        ts = t.get("time")
        return ThreadNode(
            external_id=str(int(num)),
            subject=(t.get("sub") or "").strip()[:500] or None,
            comment=Chan4Adapter._clean_comment(t.get("com")),
            timestamp=datetime.fromtimestamp(int(ts)) if ts else None,
            # У 4chan `replies` — ответы без ОП, поэтому +1
            posts_count=int(t.get("replies") or 0) + 1,
            files_count=int(t.get("images") or 0),
            views_count=0,  # 4chan не отдаёт просмотры
            # `last_modified` меняется, когда в треде появился новый пост/файл:
            # по нему планировщик понимает, что тред обновился, без обхода
            fingerprint=str(t.get("last_modified") or "") or None,
        )

    async def fetch_catalog(self, board_slug: str) -> Optional[CatalogResult]:
        """Каталог раздела: все страницы `catalog.json` (один запрос).

        `None` — каталог не прочитался (сеть/ошибка 4chan: раздел мог быть удалён).
        """
        data = await self._get_json(f"{self.base_url}/{board_slug}/catalog.json")
        if not isinstance(data, list):
            return None

        nodes: List[ThreadNode] = []
        for page in data:
            for raw in (page or {}).get("threads") or []:
                node = self._thread_node(raw)
                if node:
                    nodes.append(node)

        meta = await self._board_meta(board_slug)
        description = meta.get("meta_description") or None
        if description:
            description = description.replace("&quot;", '"').replace("&amp;", "&")
        return CatalogResult(
            threads=nodes,
            title=meta.get("title") or board_slug.upper(),
            description=description,
        )

    # ──────────────────────────── Файлы треда ────────────────────────────

    def _file_meta(self, board_slug: str, post: dict) -> Optional[FileNode]:
        """Пост с вложением → файл источника. `None` — в посте файла нет.

        У 4chan имена разделены: `filename` без расширения + `ext`, а ссылка
        собирается из `tim` (время загрузки) — так файл остаётся доступен, пока
        жив тред, и не меняется при обновлении поста.
        """
        tim = post.get("tim")
        ext_raw = str(post.get("ext") or "").lower()
        ext = ext_raw.lstrip(".")
        base = str(post.get("filename") or "").strip()
        if not tim or not base or not ext:
            return None

        filename = f"{base}.{ext}"
        media_type = MediaValidator.classify(filename)
        if not media_type:
            return None

        return FileNode(
            filename=filename,
            original_name=filename,
            source_url=f"{MEDIA_BASE}/{board_slug}/{tim}{ext_raw}",
            media_type=media_type,
            mime_type=MIME_BY_EXT.get(ext, "application/octet-stream"),
            size_bytes=int(post.get("fsize") or 0),
            md5=self._md5_hex(post.get("md5")),
            width=post.get("w"),
            height=post.get("h"),
            # Номер поста нужен для инкрементального прохода: частые сканы
            # смотрят только посты новее `last_post_num`.
            post_num=int(post.get("no") or 0),
        )

    async def fetch_thread_files(
        self, board_slug: str, external_id: str
    ) -> Optional[List[FileNode]]:
        """Файлы треда (без скачивания).

        `None` — не удалось прочитать `thread/{no}.json` (сеть/ошибка или тред уже
        уехал в архив 4chan): планировщик оставит тред в очереди, а не посчитает
        его просканированным. Пустой список — в треде действительно нет наших файлов.
        """
        data = await self._get_json(
            f"{self.base_url}/{board_slug}/thread/{external_id}.json"
        )
        if not isinstance(data, dict):
            return None

        files: List[FileNode] = []
        for post in data.get("posts") or []:
            node = self._file_meta(board_slug, post)
            if node:
                files.append(node)
        return files
