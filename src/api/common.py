# src/api/common.py
"""Общие константы и хелперы публичных роутов API."""
from typing import Iterable, Optional

from sqlalchemy import exists

from src.api.schemas import MediaOut
from src.core.config import settings
from src.core.models import Board, Media, ThreadState, User
from src.services.premium import premium_active
from src.services.s3_storage import S3Storage

# Базовый фильтр публичного показа файла.
VISIBLE_FILTER = (
    Media.is_visible.is_(True),
    Media.is_active.is_(True),
    Media.duplicate_of_id.is_(None),
)

# ─────────────────── Премиум-доступ ───────────────────

def is_locked(is_premium: bool, user: Optional[User]) -> bool:
    """Нужен ли премиум-доступ, но у пользователя его нет."""
    return bool(is_premium) and not premium_active(user)


def media_locked(media: Media, user: Optional[User]) -> bool:
    """Нужен ли премиум для полного доступа к файлу, но его у пользователя нет."""
    return is_locked(media.is_premium, user)


def visible_thread_clause():
    """SQL-условие: медиа принадлежит видимому активному треду.

    Премиум-контент остаётся в выборках: превью блюрится, полный файл
    закрыт премиум-гейтом в /asset/{thumb,web,video}, /raw и /download.
    """
    return exists().where(
        ThreadState.board_id == Media.board_id,
        ThreadState.thread_id == Media.thread_id,
        ThreadState.is_active.is_(True),
        ThreadState.is_visible.is_(True),
    )


def asset_url(media_id: int, kind: str, key: Optional[str] = None) -> str:
    """URL дериватива (thumb/web) через наш API.

    `?v=<hash>` версионирует URL: кэш nginx/браузера не отдаст устаревший
    вариант, если дериватив когда-нибудь перегенерируется.
    """
    version = ""
    if key:
        version = key.rsplit("/", 1)[-1].split("_", 1)[0][:16]
    suffix = f"?v={version}" if version else ""
    return f"/api/v1/media/{media_id}/asset/{kind}{suffix}"


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


def apply_media_urls(
    item: MediaOut,
    source: Media,
    s3: S3Storage,
    user: Optional[User] = None,
) -> MediaOut:
    """Проставляет URL оригинала и деривативов (thumb/thumb_blur/web/video).

    Для премиум-контента без активного премиума у пользователя:
    - превью подменяется на размытый вариант (`thumb_blur`), если он сгенерирован;
    - URL оригинала и полных вариантов не отдаются вовсе.
    """
    locked = media_locked(source, user)
    item.is_premium = bool(source.is_premium)
    item.locked = locked

    variants = source.variants or {}
    if source.s3_key and not locked:
        item.url = build_media_url(source.id, s3, source.s3_key)

    blur_key = variants.get("thumb_blur")
    if locked:
        # Всегда указываем публичный размытый вариант: пока блюр не сгенерирован
        # (бэкфилл не проходил), эндпоинт отдаст обычное превью, а размытие
        # добавит клиент. Реальная защита появляется после бэкфилла.
        fallback_key = blur_key or variants.get("thumb")
        if fallback_key:
            item.thumb_url = asset_url(source.id, "thumb_blur", fallback_key)
    elif variants.get("thumb"):
        item.thumb_url = asset_url(source.id, "thumb", variants["thumb"])

    if not locked:
        if source.media_type == "video":
            if variants.get("video"):
                item.web_url = asset_url(source.id, "video", variants["video"])
        elif variants.get("web"):
            item.web_url = asset_url(source.id, "web", variants["web"])
    return item


def sign_media_urls(
    items: list[MediaOut],
    sources: Iterable[Media],
    s3: S3Storage,
    user: Optional[User] = None,
) -> list[MediaOut]:
    """Прикрепляет URL файлов к элементам списка (для галерей).

    В режиме proxy клиент получает same-origin ссылку на наш /raw-эндпоинт,
    поэтому бакет и его адрес не раскрываются. Деривативы (thumb/web/video) —
    через /asset/{kind} с длинным кэшем; премиум-превью — размытый вариант.
    """
    for item, source in zip(items, sources):
        apply_media_urls(item, source, s3, user)
    return items
