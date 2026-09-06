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
    """Доска в админке: добавляет флаги управления и признак заданного кода."""
    parse_enabled: bool = True
    is_visible: bool = True
    has_access_code: bool = False


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