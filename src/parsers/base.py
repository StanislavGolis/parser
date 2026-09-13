# src/parsers/base.py
"""Контракт адаптера источника: что умеет парсер конкретного сайта.

Адаптер знает **только свой сайт**: как прочитать каталог («доски»/категории) и
как получить список файлов «треда» (треда форума, записи-«слива», категории).
Всё остальное — общее и живёт отдельно:

- `services/scan_planner.py` — план обхода, очередь, гигиена тредов, прогресс;
- `services/pipeline.py` — скачивание, валидация, S3, деривативы, запись в БД;
- `services/sources.py` — реестр источников, независимые флаги прогонов, журнал.

Поэтому новый источник = адаптер (этот контракт) + строка в `sources`.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Protocol, runtime_checkable


@dataclass
class ThreadNode:
    """«Тред» источника — то, что на сайте является единицей просмотра.

    У 2ch это тред форума, у сайтов-«сливов» — запись модели. Поля необязательные:
    источник отдаёт только то, что у него есть (у сайтов часто нет ни постов, ни
    просмотров — тогда счётчики остаются нулями).
    """

    external_id: str                    # номер треда / слаг записи (ключ на сайте)
    subject: Optional[str] = None
    comment: Optional[str] = None
    timestamp: Optional[datetime] = None
    posts_count: int = 0
    files_count: int = 0                # сколько файлов заявляет источник
    views_count: int = 0
    # Метка изменения «треда» у источника (у сайтов вместо счётчиков): например,
    # имя обложки записи. Планировщик сравнивает её, чтобы понять, что запись
    # обновилась, и поставить её в очередь.
    fingerprint: Optional[str] = None
    # Дополнительные поля сайта (сохраняются в stats/логах, в БД не обязательны)
    extra: Dict[str, object] = field(default_factory=dict)


@dataclass
class CatalogResult:
    """Каталог раздела: метаданные раздела + список «тредов»."""

    threads: List[ThreadNode] = field(default_factory=list)
    title: Optional[str] = None          # название раздела на сайте
    description: Optional[str] = None


@dataclass
class FileNode:
    """Файл источника до скачивания."""

    filename: str                        # имя файла на сайте (для расширения/типа)
    original_name: str                   # как показывать пользователю
    source_url: str                      # прямая ссылка на файл
    media_type: str                      # image | video (классификация по расширению)
    mime_type: str = "application/octet-stream"
    size_bytes: int = 0
    md5: Optional[str] = None            # если сайт отдаёт (2ch) — дедуп до скачивания
    width: Optional[int] = None
    height: Optional[int] = None
    post_num: int = 0                    # порядок внутри «треда» (для инкремента)

    def as_meta(self) -> Dict[str, object]:
        """Словарь в формате конвейера (`services/pipeline.py`).

        Конвейер намеренно работает со словарями от адаптера — так перенос из
        2ch-парсера остался дословным, а адаптеры типизированы снаружи.

        Если сайт не отдаёт md5 (у картинок без метаданных), считаем `md5(url)` и
        помечаем его синтетическим: по нему работает дедупликация **до** скачивания,
        а проверку содержимого конвейер для таких файлов не делает (SHA-256 после
        скачивания остаётся точной проверкой).
        """
        md5 = self.md5
        synthetic = not md5
        if synthetic:
            md5 = hashlib.md5(self.source_url.encode("utf-8")).hexdigest()
        return {
            "filename": self.filename,
            "original_name": self.original_name,
            "file_url": self.source_url,
            "media_type": self.media_type,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "md5": md5,
            "md5_synthetic": synthetic,
            "width": self.width,
            "height": self.height,
            "post_num": self.post_num,
        }


@runtime_checkable
class SourceAdapter(Protocol):
    """Минимальный интерфейс источника (реализуют `parsers/*`).

    `code` — код источника из реестра (`dvach`, `slivach`, …): по нему берутся
    ключи прогона (`parser:{code}:*`) и настройки (`sources.config`).
    """

    code: str

    async def __aenter__(self) -> "SourceAdapter": ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...

    def download_headers(self) -> Dict[str, str]:
        """Заголовки для скачивания файлов (Referer/UA): часть сайтов без них — 403."""
        ...

    async def fetch_catalog(self, board_slug: str) -> Optional[CatalogResult]:
        """Каталог раздела. `None` — раздел не прочитался (сеть/ошибка сайта)."""
        ...

    async def fetch_thread_files(
        self, board_slug: str, external_id: str
    ) -> Optional[List[FileNode]]:
        """Файлы «треда». `None` — список получить не удалось (тред остаётся в очереди)."""
        ...
