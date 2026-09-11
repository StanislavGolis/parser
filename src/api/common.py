# src/api/common.py
"""Общие константы и хелперы публичных роутов API."""
import hashlib
from typing import Iterable, Optional

from fastapi import Request

from src.api.schemas import MediaOut
from src.core.config import settings
from src.core.models import Board, Media
from src.services.s3_storage import S3Storage

# Базовый фильтр публичного показа файла.
VISIBLE_FILTER = (
    Media.is_visible.is_(True),
    Media.is_active.is_(True),
    Media.duplicate_of_id.is_(None),
)

# ─────────────────── Доступ к приватным доскам ───────────────────

# Префикс httpOnly-cookie доступа к приватной доске: ba_{slug} = sha256(code)
ACCESS_COOKIE_PREFIX = "ba_"
# Срок жизни cookie доступа к приватной доске (24 часа)
ACCESS_COOKIE_MAX_AGE = 24 * 60 * 60


def access_cookie_name(slug: str) -> str:
    return f"{ACCESS_COOKIE_PREFIX}{slug}"


def hash_access_code(code: str) -> str:
    """sha256-хеш кода доступа (в БД и в cookie хранится только хеш)."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def board_access_granted(request: Request, board: Board) -> bool:
    """Есть ли у запроса доступ к приватной доске (cookie с кодом)."""
    if not board.is_private:
        return True
    if not board.access_code_hash:
        return False
    cookie = request.cookies.get(access_cookie_name(board.slug))
    return bool(cookie) and cookie == board.access_code_hash


def build_media_url(
    media_id: int,
    s3: S3Storage,
    s3_key: Optional[str],
    download: bool = False,
) -> Optional[str]:
    """URL файла для клиента.

    proxy — same-origin ссылка через наш API (S3-бакет клиенту не раскрывается);
    presigned — прямая временная ссылка на объект (резервный режим).
    """
    if not s3_key:
        return None
    if settings.MEDIA_DELIVERY == "presigned":
        return s3.generate_presigned_url(s3_key)
    suffix = "?download=1" if download else ""
    return f"/api/v1/media/{media_id}/raw{suffix}"


def sign_media_urls(
    items: list[MediaOut],
    sources: Iterable[Media],
    s3: S3Storage,
) -> list[MediaOut]:
    """Прикрепляет URL файлов к элементам списка (для галерей).

    В режиме proxy клиент получает same-origin ссылку на /api/v1/media/{id}/raw,
    поэтому бакет и его адрес не раскрываются.
    """
    for item, source in zip(items, sources):
        if source.s3_key:
            item.url = build_media_url(source.id, s3, source.s3_key)
    return items
