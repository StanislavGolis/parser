# src/api/common.py
"""Общие константы и хелперы публичных роутов API."""
import hashlib
from typing import Iterable, Optional

from fastapi import Request

from src.api.schemas import MediaOut
from src.core.models import Board, Media
from src.services.b2_uploader import B2Uploader

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


def sign_media_urls(
    items: list[MediaOut],
    sources: Iterable[Media],
    b2: B2Uploader,
) -> list[MediaOut]:
    """Прикрепляет подписанные URL B2 к элементам списка (для галерей).

    Подписывание выполняется локально (без сетевых вызовов) и не требует
    повторного запроса к API на каждый файл.
    """
    for item, source in zip(items, sources):
        if source.b2_key:
            item.url = b2.generate_presigned_url(source.b2_key)
    return items
