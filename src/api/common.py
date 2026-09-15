# src/api/common.py
"""Общие константы и хелперы публичных роутов API."""
from typing import Iterable, Optional

from sqlalchemy import exists, select

from src.api.schemas import MediaOut
from src.core.config import settings
from src.core.models import Board, Media, MediaMark, ThreadState, User
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


def content_locked(media: Media, board: Optional[Board], user: Optional[User]) -> bool:
    """Премиум-гейт файла с учётом премиум-доски.

    Страховка от рассинхрона: если у файла премиум-флаг не выставлен, но сама
    доска закрыта, полный доступ всё равно требует подписки.
    """
    premium = bool(media.is_premium) or bool(board is not None and board.is_premium)
    return is_locked(premium, user)


def display_name(user: Optional[User]) -> str:
    """Как показать аккаунт человеку: email, @ник или Telegram ID.

    Аккаунты из бота создаются без email (и могут не иметь ника), поэтому у нас
    одно правило для профиля, шапки и админки: сначала почта, потом ник, потом id.
    """
    if user is None:
        return "не вошёл"
    if user.email:
        return user.email
    if user.telegram_username:
        return f"@{user.telegram_username.lstrip('@')}"
    if user.telegram_id:
        return f"Telegram {user.telegram_id}"
    return f"Аккаунт #{user.id}"


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


# Версия формата URL деривативов. Бампнуть, когда меняется сам ответ по тому же
# адресу (например, Content-Type: постеры видео отдавались как `video/mp4`, и
# браузеры/кэш держали нерабочий ответ по неизменному URL).
ASSET_URL_VERSION = "2"


def asset_url(media_id: int, kind: str, key: Optional[str] = None) -> str:
    """URL дериватива (thumb/web) через наш API.

    `?v=<hash>` версионирует URL: кэш nginx/браузера не отдаст устаревший
    вариант, если дериватив перегенерируется. Хеш берём из имени файла, а
    номер `ASSET_URL_VERSION` — от формата ответа.
    """
    version = ""
    if key:
        version = key.rsplit("/", 1)[-1].split("_", 1)[0][:16]
    if version:
        version = f"{version}-{ASSET_URL_VERSION}"
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
    board: Optional[Board] = None,
) -> MediaOut:
    """Проставляет URL оригинала и деривативов (thumb/thumb_blur/web/video).

    Для премиум-контента без активного премиума у пользователя:
    - превью подменяется на размытый вариант (`thumb_blur`), если он сгенерирован;
    - URL оригинала и полных вариантов не отдаются вовсе.

    `board` передаём там, где он известен (страница раздела и файла): премиум
    доски закрывает файл даже при рассинхроне флагов у самих файлов.
    """
    locked = content_locked(source, board, user)
    item.is_premium = bool(source.is_premium) or bool(board is not None and board.is_premium)
    item.locked = locked

    variants = source.variants or {}
    # Оригинал — премиум-функция: без подписки ссылку не отдаём вовсе, иначе её
    # легко утащить из JSON. Просмотр Free идёт через `web_url`/`thumb_url`.
    if source.s3_key and not locked and premium_active(user):
        item.url = build_media_url(source.id, s3, source.s3_key)

    blur_key = variants.get("thumb_blur")
    # Размытый вариант — публичный: он же служит плейсхолдером при загрузке
    # превью (blur-up), поэтому отдаём его отдельным полем.
    if blur_key:
        item.blur_url = asset_url(source.id, "thumb_blur", blur_key)

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


async def apply_user_flags(
    session,
    items: list[MediaOut],
    user: Optional[User],
) -> None:
    """Проставляет `marked` по данным текущего пользователя.

    Один запрос на список (а не по элементу): для страницы галереи берём
    множество media_id, отмеченных меткой.
    """
    if user is None or not items:
        return

    ids = [item.id for item in items]
    marked = set(
        (
            await session.execute(
                select(MediaMark.media_id).where(
                    MediaMark.user_id == user.id, MediaMark.media_id.in_(ids)
                )
            )
        ).scalars().all()
    )
    for item in items:
        item.marked = item.id in marked


def sign_media_urls(
    items: list[MediaOut],
    sources: Iterable[Media],
    s3: S3Storage,
    user: Optional[User] = None,
    board: Optional[Board] = None,
) -> list[MediaOut]:
    """Прикрепляет URL файлов к элементам списка (для галерей).

    В режиме proxy клиент получает same-origin ссылку на наш /raw-эндпоинт,
    поэтому бакет и его адрес не раскрываются. Деривативы (thumb/web/video) —
    через /asset/{kind} с длинным кэшем; премиум-превью — размытый вариант.
    """
    for item, source in zip(items, sources):
        apply_media_urls(item, source, s3, user, board)
    return items
