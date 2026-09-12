# src/api/schemas.py
"""Pydantic-схемы ответов API."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class BoardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    description: Optional[str] = None
    media_count: int = 0
    is_private: bool = False


class AdminBoardOut(BoardOut):
    """Доска в админке: флаги управления и живая статистика контента."""
    parse_enabled: bool = True
    is_visible: bool = True
    has_access_code: bool = False
    sort_order: int = 0
    parse_mode: str = "all"  # all | selected

    # Статистика (агрегируется из БД)
    media_total: int = 0
    media_downloaded: int = 0
    media_in_s3: int = 0
    media_missing: int = 0
    threads_active: int = 0
    threads_parsing: int = 0
    files_in_catalog: int = 0
    last_scan: Optional[datetime] = None
    views_total: int = 0
    downloads_total: int = 0


class SystemTotals(BaseModel):
    boards_total: int = 0
    boards_parsed: int = 0
    media_total: int = 0
    media_in_s3: int = 0
    media_downloaded: int = 0
    media_missing: int = 0
    threads_active: int = 0
    threads_parsing: int = 0
    files_in_catalog: int = 0
    views_total: int = 0
    downloads_total: int = 0


class AdminOverview(BaseModel):
    """Снапшот для админ-панели (обновляется polling'ом)."""
    generated_at: datetime
    totals: SystemTotals
    boards: List[AdminBoardOut]
    parser_up: bool = False          # демон парсера запущен (heartbeat parser:up)
    parser_enabled: bool = False     # парсинг включён (parser:enabled)
    parser_alive: bool = False       # парсер прямо сейчас активно работает
    parser_current_board: Optional[str] = None


class ForumBoardOut(BaseModel):
    """Доска форума (из index.json двача), сопоставленная с нашей БД."""
    slug: str
    name: Optional[str] = None
    category: Optional[str] = None
    threads_on_forum: int = 0
    in_db: bool = False
    parse_enabled: bool = False
    is_visible: bool = False
    is_private: bool = False
    media_total: int = 0
    media_in_s3: int = 0
    threads_active: int = 0


class BoardCreate(BaseModel):
    slug: str
    name: Optional[str] = None  # настоящее название (из index.json), если известно


class BoardUpdate(BaseModel):
    parse_enabled: Optional[bool] = None
    is_visible: Optional[bool] = None
    is_private: Optional[bool] = None
    parse_mode: Optional[str] = None  # all | selected
    title: Optional[str] = None
    # Новый код доступа. Пустая строка/null = сбросить код (доступ закрывается).
    access_code: Optional[str] = None


class ThreadUpdate(BaseModel):
    """Флаги треда и/или код доступа к приватному треду."""
    parse_enabled: Optional[bool] = None
    is_visible: Optional[bool] = None
    is_private: Optional[bool] = None
    # Непустая строка — установить/сменить код; пустая строка — сбросить код.
    access_code: Optional[str] = None


class ThreadBulkUpdate(BaseModel):
    """Массовое изменение флагов выбранных тредов одной доски."""
    thread_ids: List[int]
    parse_enabled: Optional[bool] = None
    is_visible: Optional[bool] = None
    is_private: Optional[bool] = None


class BoardReorder(BaseModel):
    """Новый порядок парсинга: слаги досок в требуемой последовательности."""
    slugs: List[str]


class ResetResult(BaseModel):
    deleted_boards: int = 0
    deleted_objects: int = 0


class AccessRequest(BaseModel):
    code: str


class AccessResult(BaseModel):
    granted: bool


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    board_id: int
    thread_id: int
    original_name: str
    file_size: int
    mime_type: str
    media_type: str
    width: Optional[int] = None
    height: Optional[int] = None
    views_count: int
    downloads_count: int
    popularity_score: float
    created_at: datetime
    # Технические данные (для техпанели lightbox)
    source_md5: Optional[str] = None
    file_hash: Optional[str] = None
    url: Optional[str] = None  # подписанный URL (для media/{id} и download)


class MediaListOut(BaseModel):
    items: List[MediaOut]
    page: int
    per_page: int
    total: int


class ThreadOut(BaseModel):
    """Тред доски с агрегированной статистикой файлов (для сайта/админки)."""
    model_config = ConfigDict(from_attributes=True)

    board_id: int
    thread_id: int
    subject: Optional[str] = None
    comment: Optional[str] = None
    posts_count: int = 0
    files_count: int = 0          # файлов в каталоге на последний скан (обнаружено)
    thread_timestamp: Optional[datetime] = None
    last_scanned_at: Optional[datetime] = None
    is_active: bool = True

    # Управление (админка) и приватность
    parse_enabled: bool = True
    is_visible: bool = True
    is_private: bool = False
    has_access_code: bool = False

    # Статистика по файлам из нашей БД
    media_total: int = 0          # всего записей в БД
    media_downloaded: int = 0     # скачано (без выгрузки в S3)
    media_in_s3: int = 0          # загружено в S3 (uploaded+verified)
    media_missing: int = 0        # файл потерян
    media_visible: int = 0        # видимых на сайте

    # Несколько последних файлов треда для превью
    preview: List[MediaOut] = []


class ThreadListOut(BaseModel):
    items: List[ThreadOut]
    page: int
    per_page: int
    total: int


class MediaDetailOut(MediaOut):
    board_slug: Optional[str] = None
    duplicate_of_id: Optional[int] = None


class ViewResult(BaseModel):
    media_id: int
    counted: bool         # True — счётчик увеличен, False — дубль за период


class DownloadResult(BaseModel):
    media_id: int
    counted: bool
    url: str


class TopItem(MediaOut):
    pass


class ToggleResult(BaseModel):
    id: int
    is_visible: bool