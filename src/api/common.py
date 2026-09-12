# src/api/common.py
"""Общие константы и хелперы публичных роутов API."""
import hashlib
from typing import Iterable, Optional

from fastapi import Request
from sqlalchemy import exists, or_, select

from src.api.schemas import MediaOut
from src.core.config import settings
from src.core.models import Board, Media, ThreadState
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


# ─────────────────── Доступ к приватным тредам ───────────────────

# Префикс httpOnly-cookie доступа к приватному треду: bt_{board_id}_{thread_id}
THREAD_ACCESS_COOKIE_PREFIX = "bt_"


def thread_access_cookie_name(board_id: int, thread_id: int) -> str:
    return f"{THREAD_ACCESS_COOKIE_PREFIX}{board_id}_{thread_id}"


def thread_access_granted(request: Request, board: Board, thread: ThreadState) -> bool:
    """Есть ли у запроса доступ к приватному треду.

    Доступ даёт либо персональный cookie треда, либо (если доска приватная)
    действующий код доски — он открывает все её треды.
    """
    if not thread.is_private:
        return True
    if board.is_private and board_access_granted(request, board):
        return True
    if not thread.access_code_hash:
        return False
    cookie = request.cookies.get(thread_access_cookie_name(board.id, thread.thread_id))
    return bool(cookie) and cookie == thread.access_code_hash


async def allowed_private_thread_ids(session, request: Request, board: Board) -> set:
    """Набор внешних thread_id приватных тредов доски, доступных этому запросу."""
    result = await session.execute(
        select(ThreadState.thread_id, ThreadState.access_code_hash).where(
            ThreadState.board_id == board.id,
            ThreadState.is_private.is_(True),
        )
    )
    board_ok = board.is_private and board_access_granted(request, board)
    allowed: set = set()
    for thread_id, code_hash in result.all():
        if board_ok:
            allowed.add(int(thread_id))
            continue
        if not code_hash:
            continue
        cookie = request.cookies.get(thread_access_cookie_name(board.id, int(thread_id)))
        if cookie and cookie == code_hash:
            allowed.add(int(thread_id))
    return allowed


def visible_thread_clause(allowed_private_ids: Optional[set] = None):
    """SQL-условие: медиа принадлежит видимому треду.

    Скрытые треды (is_visible=False) исключаются всегда; приватные —
    только если их thread_id есть в allowed_private_ids (доступ подтверждён).
    """
    if allowed_private_ids:
        priv_cond = or_(
            ThreadState.is_private.is_(False),
            ThreadState.thread_id.in_(allowed_private_ids),
        )
    else:
        priv_cond = ThreadState.is_private.is_(False)

    return exists().where(
        ThreadState.board_id == Media.board_id,
        ThreadState.thread_id == Media.thread_id,
        ThreadState.is_active.is_(True),
        ThreadState.is_visible.is_(True),
        priv_cond,
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


def apply_media_urls(item: MediaOut, source: Media, s3: S3Storage) -> MediaOut:
    """Проставляет URL оригинала и деривативов (thumb/web) для одного файла."""
    if source.s3_key:
        item.url = build_media_url(source.id, s3, source.s3_key)
    variants = source.variants or {}
    if variants.get("thumb"):
        item.thumb_url = asset_url(source.id, "thumb", variants["thumb"])
    if variants.get("web"):
        item.web_url = asset_url(source.id, "web", variants["web"])
    return item


def sign_media_urls(
    items: list[MediaOut],
    sources: Iterable[Media],
    s3: S3Storage,
) -> list[MediaOut]:
    """Прикрепляет URL файлов к элементам списка (для галерей).

    В режиме proxy клиент получает same-origin ссылку на наш /raw-эндпоинт,
    поэтому бакет и его адрес не раскрываются. Деривативы (thumb/web) —
    через /asset/{kind} с длинным кэшем.
    """
    for item, source in zip(items, sources):
        apply_media_urls(item, source, s3)
    return items
