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

    # Статистика (агрегируется из БД)
    media_total: int = 0
    media_downloaded: int = 0
    media_in_b2: int = 0
    media_missing: int = 0
    threads_active: int = 0
    files_in_catalog: int = 0
    last_scan: Optional[datetime] = None
    views_total: int = 0
    downloads_total: int = 0


class SystemTotals(BaseModel):
    boards_total: int = 0
    boards_parsed: int = 0
    media_total: int = 0
    media_in_b2: int = 0
    media_downloaded: int = 0
    media_missing: int = 0
    threads_active: int = 0
    files_in_catalog: int = 0
    views_total: int = 0
    downloads_total: int = 0


class AdminOverview(BaseModel):
    """Снапшот для админ-панели (обновляется polling'ом)."""
    generated_at: datetime
    totals: SystemTotals
    boards: List[AdminBoardOut]


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
    media_in_b2: int = 0
    threads_active: int = 0


class BoardCreate(BaseModel):
    slug: str


class BoardUpdate(BaseModel):
    parse_enabled: Optional[bool] = None
    is_visible: Optional[bool] = None
    is_private: Optional[bool] = None
    # Новый код доступа. Пустая строка/null = сбросить код (доступ закрывается).
    access_code: Optional[str] = None


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

    # Статистика по файлам из нашей БД
    media_total: int = 0          # всего записей в БД
    media_downloaded: int = 0     # скачано (без выгрузки в B2)
    media_in_b2: int = 0          # загружено в B2 (uploaded+verified)
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