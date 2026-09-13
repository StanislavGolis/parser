# src/parsers/slivach.py
"""Адаптер источника slivach.com (HTML, DataLife Engine).

Разведка сайта (13.09.2026, `dredge-backups/probe_slivach*.sh`):

- категории — пункты меню `/category/<slug>/` (modeli, asmr, aktrisy, …);
- в категории — карточки записей с пагинацией `/category/<slug>/page/N/`;
  карточка: ссылка `/<model>-sliv/`, заголовок `a.xsliv-item-title`,
  обложка `/imgprofile-…/images/posts/<model>/thumbs/<файл>.webp`;
- внутри записи — галереи `class="girls-gallery"`: картинки
  `/…images/posts/<model>/<файл>-<W>x<H>.webp` и видео
  `/videos/posts/<model>/video-<model>-<ts>-<N>.mp4`.

Особенности источника, которые здесь учтены:

- **видео отдаётся только с `Referer`** (иначе 403) — см. `download_headers()`;
- **оригиналов нет**: максимум — webp ~810–2000 px и mp4, значит «оригинал» = то,
  что отдаёт сайт;
- **md5 нет**: дедуп до скачивания — по `md5(url)` (`md5_synthetic` в метаданных),
  точная дедупликация — по SHA-256 уже скачанного файла;
- **размеров и дат нет**: `size_bytes` неизвестен (валидатор не режет по весу),
  дата материала выводится из timestamp в имени файла (`YYYYMMDDHHMMSS`);
- **fingerprint записи** — имя обложки в карточке категории: она стабильна между
  запросами и меняется, когда в записи появляются новые файлы (планировщик
  сравнивает fingerprint вместо счётчиков, которых сайт не отдаёт).

Маппинг (M2): категория → раздел («доска», slug `slivach-<категория>`),
запись-«слив» → «тред» (`external_id` = `alena-omovich-sliv`), файлы записи → файлы.
"""
import asyncio
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import aiohttp
from selectolax.parser import HTMLParser

from src.core.config import settings
from src.parsers.base import CatalogResult, FileNode, ThreadNode

# Категории сайта (пункты меню). Используются, если в конфиге источника
# (`sources.config["boards"]`) свой список не задан.
DEFAULT_CATEGORIES = [
    "modeli",
    "asmr",
    "aktrisy",
    "pevitsy",
    "sportsmenki",
    "blogershi",
    "strimershi",
    "kospley",
    "tiktokershi",
    "znamenitosti",
]

IMAGE_EXTS = (".webp", ".jpg", ".jpeg", ".png", ".gif")
VIDEO_EXTS = (".mp4", ".webm")

RECORD_RE = re.compile(r"^/([a-z0-9-]+-sliv)/?$")
COVER_TS_RE = re.compile(r"-(\d{14})-(\d+)-")
DIMS_RE = re.compile(r"-(\d{3,5})x(\d{3,5})\.(?:webp|jpe?g|png|gif)$")
# Одна и та же фотография лежит на сайте в нескольких размерах
# (`…-12-810x1080.webp`, `…-12-960x1280.webp`): «личность» файла — имя без -WxH
VARIANT_RE = re.compile(r"-\d{3,5}x\d{3,5}(?=\.[a-z0-9]+$)", re.IGNORECASE)


class SlivachAdapter:
    """Парсер slivach.com: категории → записи-«сливы» → файлы записи."""

    code = "slivach"
    BASE_URL = "https://slivach.com"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"
    )

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        max_pages: int = 20,
        max_records: int = 0,
        include_images: bool = True,
        include_video: bool = True,
        **_options,
    ):
        # base_url приходит из реестра (`sources.base_url`): сайт переезжал между
        # доменами, поэтому адрес задаётся конфигом, а не зашит в код
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        # Лимиты обхода (конфиг источника): страниц категории и записей на категорию
        self.max_pages = max(1, int(max_pages))
        self.max_records = max(0, int(max_records))  # 0 — без ограничения
        self.include_images = bool(include_images)
        self.include_video = bool(include_video)
        self.http_session: Optional[aiohttp.ClientSession] = None

    @property
    def default_boards(self) -> List[str]:
        """Разделы источника по умолчанию — категории сайта со своим префиксом.

        Префикс нужен, чтобы слаги не пересекались с досками других источников
        (на 2ch, например, есть раздел `/asmr`): `slivach-asmr`.
        """
        return [f"{self.code}-{category}" for category in DEFAULT_CATEGORIES]

    async def __aenter__(self) -> "SlivachAdapter":
        self.http_session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.http_session:
            await self.http_session.close()

    def download_headers(self) -> Dict[str, str]:
        """Сайт отдаёт видео только с Referer (без него — 403)."""
        return {"Referer": f"{self.base_url}/"}

    # ───────────────────────── HTTP и разбор ─────────────────────────

    async def _get_html(self, url: str) -> Optional[str]:
        """Скачивает страницу. `None` — сеть/ошибка сайта (решает вызывающий)."""
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {"User-Agent": self.USER_AGENT, "Referer": f"{self.base_url}/"}
            async with self.http_session.get(url, timeout=timeout, headers=headers) as response:
                response.raise_for_status()
                return await response.text()
        except Exception as e:  # noqa: BLE001
            print(f"   [err] HTTP {url}: {e}")
            return None

    async def _pace(self) -> None:
        """Пауза между запросами к сайту (вежливость: `REQUEST_DELAY`)."""
        if settings.REQUEST_DELAY > 0:
            await asyncio.sleep(settings.REQUEST_DELAY)

    @staticmethod
    def _clean(text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        return re.sub(r"\s+", " ", text).strip() or None

    def _category(self, board_slug: str) -> str:
        """Slug раздела → категория сайта.

        Разделы источника называются `slivach-<категория>`; если префикса нет,
        slug считается самой категорией (ручное создание раздела в админке).
        """
        prefix = f"{self.code}-"
        return board_slug[len(prefix):] if board_slug.startswith(prefix) else board_slug

    @staticmethod
    def _file_ts(name: str) -> Optional[datetime]:
        """Дата файла из имени (`…-20251023213355-…`); сайт отдаёт московское время."""
        match = COVER_TS_RE.search(name)
        if not match:
            return None
        try:
            return datetime.strptime(match.group(1), "%Y%m%d%H%M%S") - timedelta(hours=3)
        except ValueError:
            return None


    # ─────────────────────── Каталог категории ───────────────────────

    def _parse_card(self, link) -> Optional[ThreadNode]:
        """Карточка записи → «тред» источника (категория = раздел)."""
        href = link.attributes.get("href") or ""
        match = RECORD_RE.match(href)
        if not match:
            return None
        external_id = match.group(1)

        # Обложка лежит в блоке карточки: берём её как fingerprint (у сайта нет
        # ни счётчиков файлов, ни дат обновления — а имя обложки меняется, когда
        # в записи появляются новые файлы)
        cover = None
        index = None
        block = link.parent
        for _ in range(3):  # карточка может быть в 1–3 уровнях вложенности
            if block is None:
                break
            img = block.css_first("img[src*='/images/posts/']")
            if img is not None:
                cover = img.attributes.get("src")
                break
            block = block.parent

        name = (cover or "").rsplit("/", 1)[-1]
        ts_match = COVER_TS_RE.search(name)
        if ts_match:
            index = int(ts_match.group(2))

        return ThreadNode(
            external_id=external_id,
            subject=self._clean(link.text()),
            # Дата материала — из имени обложки; самих дат на сайте нет
            timestamp=self._file_ts(name),
            fingerprint=name or None,
            extra={"cover": cover, "index": index},
        )

    async def fetch_catalog(self, board_slug: str) -> Optional[CatalogResult]:
        """Каталог категории: все записи (с обходом пагинации `/page/N/`).

        `None` — категория не прочиталась (сеть/ошибка сайта): планировщик покажет
        «каталог недоступен» и не тронет уже сохранённые записи.
        """
        category = self._category(board_slug)
        first_url = f"{self.base_url}/category/{category}/"
        first_html = await self._get_html(first_url)
        if first_html is None:
            return None

        tree = HTMLParser(first_html)
        title = None
        h1 = tree.css_first("h1")
        if h1 is not None:
            title = self._clean(h1.text())
        description = None
        desc = tree.css_first(".listing-description-top p")
        if desc is not None:
            description = self._clean(desc.text())

        # Сколько страниц в категории — по ссылкам пагинации (page/N/)
        page_re = re.compile(rf"/category/{re.escape(category)}/page/(\d+)/")
        last_page = 1
        for anchor in tree.css("a[href]"):
            found = page_re.search(anchor.attributes.get("href") or "")
            if found:
                last_page = max(last_page, int(found.group(1)))
        last_page = min(last_page, self.max_pages)

        threads: List[ThreadNode] = []
        seen: set[str] = set()

        def collect(html: str) -> None:
            page_tree = HTMLParser(html)
            for link in page_tree.css("a.xsliv-item-title[href]"):
                node = self._parse_card(link)
                if node is None or node.external_id in seen:
                    continue
                seen.add(node.external_id)
                threads.append(node)

        collect(first_html)
        for page in range(2, last_page + 1):
            if self.max_records and len(threads) >= self.max_records:
                break
            await self._pace()
            html = await self._get_html(f"{self.base_url}/category/{category}/page/{page}/")
            if html is None:
                break  # страница не отдалась — не теряем уже собранное
            collect(html)

        if self.max_records:
            threads = threads[: self.max_records]

        print(
            f"   [cat]  Категория {category}: {len(threads)} записей "
            f"(страниц просмотрено: {last_page}"
            f"{', лимит max_pages' if last_page >= self.max_pages else ''})"
        )
        return CatalogResult(threads=threads, title=title, description=description)


    # ──────────────────────── Файлы записи ───────────────────────────

    def _image_node(self, path: str) -> FileNode:
        """Картинка галереи → файл источника (размер и md5 сайт не отдаёт)."""
        full = path if path.startswith("http") else f"{self.base_url}{path}"
        name = full.rsplit("/", 1)[-1] or "image"
        width = height = None
        dims = DIMS_RE.search(name)
        if dims:
            width, height = int(dims.group(1)), int(dims.group(2))
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        return FileNode(
            filename=name,
            original_name=name,
            source_url=full,
            media_type="image",
            mime_type="image/webp" if ext == "webp" else f"image/{ext or 'jpeg'}",
            # Размер сайт не отдаёт: 0 = «неизвестен», валидатор не режет по весу
            # (реальная проверка — после скачивания, через Pillow)
            size_bytes=0,
            # md5 сайт тоже не отдаёт: конвейер считает md5(url) и помечает его
            # синтетическим (md5_synthetic), дедуп по содержимому — по SHA-256
            md5=None,
            width=width,
            height=height,
        )

    def _video_node(self, path: str) -> FileNode:
        """Видео записи → файл источника (mp4, требует Referer при скачивании)."""
        full = path if path.startswith("http") else f"{self.base_url}{path}"
        name = full.rsplit("/", 1)[-1] or "video"
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        return FileNode(
            filename=name,
            original_name=name,
            source_url=full,
            media_type="video",
            mime_type="video/mp4" if ext == "mp4" else f"video/{ext or 'mp4'}",
            size_bytes=0,
            md5=None,
        )

    async def fetch_thread_files(
        self, board_slug: str, external_id: str
    ) -> Optional[List[FileNode]]:
        """Файлы записи: картинки галерей + видео.

        `None` — страница не прочиталась (планировщик оставит тред в очереди).
        Превью сайдбара («похожие») отсекаем по их префиксу `imgprofile-`.
        """
        url = f"{self.base_url}/{external_id.strip('/')}/"
        html = await self._get_html(url)
        if html is None:
            return None

        tree = HTMLParser(html)
        files: List[FileNode] = []
        seen: set[str] = set()
        # Варианты одной фотографии (разные размеры) сворачиваем в один файл,
        # оставляя самый крупный: иначе в БД попадают дубли одного снимка
        best_image: Dict[str, FileNode] = {}
        order: List[str] = []

        def add_image(path: str) -> None:
            if path in seen:
                return
            seen.add(path)
            node = self._image_node(path)
            identity = VARIANT_RE.sub("", node.filename)
            previous = best_image.get(identity)
            if previous is None:
                best_image[identity] = node
                order.append(identity)
                return
            current_area = (node.width or 0) * (node.height or 0)
            previous_area = (previous.width or 0) * (previous.height or 0)
            if current_area > previous_area:
                best_image[identity] = node  # тот же снимок, но крупнее

        if self.include_images:
            for node in tree.css("img[src], a[href]"):
                raw = node.attributes.get("src") or node.attributes.get("href") or ""
                if "/images/posts/" not in raw or "imgprofile-" in raw:
                    continue
                add_image(raw)

        if self.include_video:
            for node in tree.css("a[href], source[src]"):
                raw = node.attributes.get("href") or node.attributes.get("src") or ""
                if "/videos/posts/" in raw and raw not in seen:
                    seen.add(raw)
                    files.append(self._video_node(raw))

        # Порядок: сначала фотографии (в порядке появления на странице), затем видео
        files = [best_image[identity] for identity in order] + files

        # Порядок файлов — как на странице: по нему работает дешёвый инкремент
        # планировщика (`last_post_num`): у новых файлов номер больше сохранённого
        for position, node in enumerate(files, start=1):
            node.post_num = position

        print(
            f"   [rec]  Запись {external_id}: файлов {len(files)} "
            f"(фото {len(best_image)}, видео {len(files) - len(best_image)})"
        )
        return files

