# src/services/telegram_service.py
"""Ядро менеджера Telegram-канала: подбор файлов, тизер, публикация, расписание.

Вынесено из роута `admin_telegram.py`, потому что публикация нужна не только
админке: планировщик (`src/tools/telegram_autopost.py`) публикует отложенные
посты и собирает черновики для карантина — с теми же правилами:

* канал — витрина закрытого архива, пост ведёт в бота;
* картинка собирается из наших превью и размывается;
* каждая отправка фиксируется в `telegram_posts` со статусом и ошибкой.

Статусы поста: `draft` (черновик/карантин) → `scheduled` → `published`;
`failed` (Telegram не принял), `deleted`, `cancelled` (отменён до публикации),
`rejected` (карантин отклонён админом).
"""
from __future__ import annotations

import asyncio
import os
import random
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import VISIBLE_FILTER, visible_thread_clause
from src.core.config import settings
from src.core.models import (
    Board,
    Giveaway,
    GiveawayEntry,
    Media,
    TelegramAutopost,
    TelegramPost,
    User,
)
from src.services import telegram_api, telegram_publisher
from src.services.analytics import record_audit
from src.services.s3_storage import S3Storage

MAX_TILES = 4
KINDS = ("teaser", "digest", "announce")
IMAGE_MODES = ("mosaic", "single", "none")
PERIODS = ("day", "week")
# Карантин: сколько держим черновик до публикации, если админ не ответил в ЛС
AUTOPOST_CHECK_MINUTES = 5
QUIET_HOURS_DEFAULT = (1, 8)  # ночью не публикуем (МСК)


def channel_name() -> Optional[str]:
    """Имя канала без собаки (для журнала и ссылок)."""
    return (settings.TELEGRAM_CHANNEL or "").lstrip("@") or None


def link_for(post: TelegramPost) -> Optional[str]:
    """Ссылка на сообщение канала (если он публичный и мы знаем message_id)."""
    channel = (post.channel or "").lstrip("@")
    if channel and post.message_id and not channel.startswith("-"):
        return f"https://t.me/{channel}/{post.message_id}"
    return None


async def load_media(session: AsyncSession, media_ids: List[int], limit: int = MAX_TILES) -> List[Media]:
    """Файлы для тизера — в порядке выбора, только видимые и уникальные."""
    ordered: List[int] = []
    for media_id in media_ids:
        if media_id not in ordered:
            ordered.append(media_id)
    if not ordered:
        return []

    rows = await session.execute(
        select(Media).where(
            Media.id.in_(ordered[:limit]), *VISIBLE_FILTER, visible_thread_clause()
        )
    )
    found = {item.id: item for item in rows.scalars().all()}
    return [found[media_id] for media_id in ordered if media_id in found][:limit]


async def latest_media(session: AsyncSession, limit: int = MAX_TILES) -> List[Media]:
    """Самые свежие видимые файлы: подстановка, когда админ ничего не выбрал."""
    rows = await session.execute(
        select(Media)
        .where(*VISIBLE_FILTER, visible_thread_clause(), Media.is_premium.is_(False))
        .order_by(Media.created_at.desc(), Media.id.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())


async def digest_media(
    session: AsyncSession,
    *,
    period: str = "day",
    board: Optional[str] = None,
    limit: int = MAX_TILES,
) -> List[Media]:
    """Подборка для дайджеста: файлы за период, лучшие — по просмотрам.

    «За сутки»/«за неделю» считаем по дате появления файла в архиве: это честно
    отражает «что нового», а порядок задаём по просмотрам — сверху то, что смотрят.
    """
    days = 7 if period == "week" else 1
    since = datetime.utcnow() - timedelta(days=days)
    query = (
        select(Media)
        .join(Board, Board.id == Media.board_id)
        .where(
            *VISIBLE_FILTER,
            visible_thread_clause(),
            Media.is_premium.is_(False),
            Board.is_visible.is_(True),
            Media.created_at >= since,
        )
        .order_by(Media.views_count.desc(), Media.created_at.desc(), Media.id.desc())
        .limit(limit)
    )
    if board:
        query = query.where(Board.slug == board)

    items = list((await session.execute(query)).scalars().all())
    if items:
        return items
    # За период ничего не появилось — не оставляем админа с пустым экраном
    return await latest_media(session, limit)


async def board_slugs(session: AsyncSession, items: List[Media]) -> List[str]:
    """Слаги разделов выбранных файлов — в подписи перечисляем разделы."""
    board_ids = sorted({item.board_id for item in items})
    if not board_ids:
        return []
    rows = await session.execute(
        select(Board.slug).where(Board.id.in_(board_ids)).order_by(Board.slug)
    )
    return [slug for (slug,) in rows.all()]


def caption_for(
    *,
    kind: str,
    boards: List[str],
    total: int,
    text: Optional[str] = None,
    period: Optional[str] = None,
) -> str:
    """Подпись поста по шаблону типа (teaser | digest | announce)."""
    return telegram_publisher.build_caption(
        kind,
        boards=boards,
        media_total=total,
        media_today=0,
        text=text,
        bot_username=settings.TELEGRAM_BOT_USERNAME,
        period=period,
    )


def button_for(text: Optional[str], url: Optional[str]) -> tuple[str, str]:
    """Кнопка под постом: по умолчанию ведёт в бота (сайт закрытый)."""
    label = (text or "").strip()
    if not label and settings.TELEGRAM_BOT_USERNAME:
        label = "Открыть в боте"
    target = (url or "").strip() or telegram_publisher.bot_url(settings.TELEGRAM_BOT_USERNAME)
    return label, target


async def tile_bytes(s3: S3Storage, items: List[Media], limit: int = MAX_TILES) -> List[bytes]:
    """Байты превью выбранных файлов: `thumb`, иначе размытый вариант.

    У видео `thumb` — это постер, поэтому отдельной ветки не нужно. Файлы качаем
    во временный каталог: дальше с ними работает PIL.
    """
    picked = [item for item in items if item.s3_key][:limit]
    if not picked:
        return []

    payloads: List[bytes] = []
    with tempfile.TemporaryDirectory() as tmp:
        for index, item in enumerate(picked):
            variants = item.variants or {}
            key = variants.get("thumb") or variants.get("thumb_blur")
            if not key:
                continue
            path = Path(tmp) / f"tile_{index}"
            try:
                if await s3.download_to_file(key, path):
                    payloads.append(path.read_bytes())
            except Exception:  # noqa: BLE001 — один битый дериватив не ломает пост
                continue
            finally:
                path.unlink(missing_ok=True)
    return payloads


async def render_image(
    s3: S3Storage, items: List[Media], mode: str, blur: int
) -> Optional[bytes]:
    """Картинка тизера: мозаика 2×2, одиночный кадр или без картинки."""
    if mode == "none":
        return None
    tiles = await tile_bytes(s3, items, 1 if mode == "single" else MAX_TILES)
    if not tiles:
        return None
    return await asyncio.to_thread(telegram_publisher.build_teaser_image, tiles, blur=blur)


async def _deliver(
    session: AsyncSession,
    s3: S3Storage,
    post: TelegramPost,
    items: List[Media],
    *,
    label: str,
    url: str,
    blur: int = telegram_publisher.DEFAULT_BLUR,
) -> None:
    """Отправляет пост в канал и проставляет статус — общий путь для всех публикаций."""
    if not telegram_api.is_configured():
        post.status = "failed"
        post.error = "Публикация не настроена: нет токена бота или канала"
        await record_audit(session, action="telegram.post", target="—", details="не настроено")
        return

    try:
        image = await render_image(s3, items, post.image_mode or "mosaic", blur)
        if image:
            result = await telegram_api.send_photo(
                photo=image, caption=post.caption, button_text=label, button_url=url
            )
        else:
            result = await telegram_api.send_message(
                text=post.caption, button_text=label, button_url=url
            )
        post.status = "published"
        post.published_at = datetime.utcnow()
        post.message_id = result.get("message_id")
        post.error = None
        details = f"{post.kind}: опубликовано (файлов: {len(items)})"
    except Exception as exc:  # noqa: BLE001 — текст ошибки нужен в журнале и админке
        post.status = "failed"
        post.error = str(exc)[:500]
        details = f"{post.kind}: ошибка — {post.error}"

    await record_audit(
        session, action="telegram.post", target=str(post.message_id or "—"), details=details
    )


def build_post(
    *,
    kind: str,
    caption: str,
    media_ids: List[int],
    image_mode: str,
    button_text: str,
    button_url: str,
    actor: str,
    status: str = "draft",
    scheduled_at: Optional[datetime] = None,
) -> TelegramPost:
    """Собирает запись журнала (в БД попадает вместе с публикацией или расписанием)."""
    return TelegramPost(
        kind=kind if kind in KINDS else "teaser",
        caption=caption,
        media_ids=media_ids or None,
        image_mode=image_mode if image_mode in IMAGE_MODES else "mosaic",
        button_text=button_text or None,
        button_url=button_url or None,
        channel=channel_name(),
        created_by=actor,
        status=status,
        scheduled_at=scheduled_at,
    )


async def publish_now(
    session: AsyncSession,
    s3: S3Storage,
    *,
    kind: str,
    media_ids: List[int],
    image_mode: str = "mosaic",
    blur: int = telegram_publisher.DEFAULT_BLUR,
    text: Optional[str] = None,
    period: Optional[str] = None,
    button_text: Optional[str] = None,
    button_url: Optional[str] = None,
    actor: str = "admin-token",
) -> TelegramPost:
    """Публикует пост в канал сейчас же (ручная публикация из композера)."""
    items = await load_media(session, media_ids)
    if not items:
        items = await latest_media(session)

    boards = await board_slugs(session, items)
    caption = caption_for(kind=kind, boards=boards, total=len(items), text=text, period=period)
    label, url = button_for(button_text, button_url)

    post = build_post(
        kind=kind,
        caption=caption,
        media_ids=[item.id for item in items],
        image_mode=image_mode,
        button_text=label,
        button_url=url,
        actor=actor,
    )
    session.add(post)
    await _deliver(session, s3, post, items, label=label, url=url, blur=max(0, min(24, blur)))
    await session.commit()
    await session.refresh(post)
    return post


async def schedule_post(
    session: AsyncSession,
    *,
    scheduled_at: datetime,
    kind: str,
    media_ids: List[int],
    image_mode: str = "mosaic",
    text: Optional[str] = None,
    period: Optional[str] = None,
    button_text: Optional[str] = None,
    button_url: Optional[str] = None,
    actor: str = "admin-token",
) -> TelegramPost:
    """Ставит пост в очередь: планировщик отправит его в назначенное время.

    Подпись и список файлов собираем заранее и сохраняем в записи — в час публикации
    не зависим от того, что ещё появилось в архиве.
    """
    items = await load_media(session, media_ids)
    if not items:
        items = await latest_media(session)

    boards = await board_slugs(session, items)
    caption = caption_for(kind=kind, boards=boards, total=len(items), text=text, period=period)
    label, url = button_for(button_text, button_url)

    post = build_post(
        kind=kind,
        caption=caption,
        media_ids=[item.id for item in items],
        image_mode=image_mode,
        button_text=label,
        button_url=url,
        actor=actor,
        status="scheduled",
        scheduled_at=scheduled_at,
    )
    session.add(post)
    await record_audit(
        session,
        action="telegram.schedule",
        target=str(post.id),
        details=f"{post.kind}: в очередь на {scheduled_at:%d.%m %H:%M} UTC",
    )
    await session.commit()
    await session.refresh(post)
    return post


async def due_posts(session: AsyncSession, limit: int = 5) -> List[TelegramPost]:
    """Отложенные посты, которым пора выходить."""
    rows = await session.execute(
        select(TelegramPost)
        .where(
            TelegramPost.status == "scheduled",
            TelegramPost.scheduled_at.isnot(None),
            TelegramPost.scheduled_at <= datetime.utcnow(),
        )
        .order_by(TelegramPost.scheduled_at)
        .limit(limit)
    )
    return list(rows.scalars().all())


async def publish_scheduled(session: AsyncSession, s3: S3Storage, post: TelegramPost) -> TelegramPost:
    """Публикует отложенный пост (вызывает планировщик)."""
    items = await load_media(session, list(post.media_ids or []))
    if not items:
        items = await latest_media(session)
    await _deliver(
        session, s3, post, items, label=post.button_text or "", url=post.button_url or ""
    )
    await session.commit()
    await session.refresh(post)
    return post


# ── Карантин и автопостинг ───────────────────────────────────────────

async def admin_chat_ids(session: AsyncSession) -> List[str]:
    """Кому уходит карантин: админам с привязанным Telegram и «страховочному» чату.

    Админ может входить на сайт по паролю, не привязывая Telegram, — тогда черновик
    доставлять некому. Поэтому есть страховочный получатель: id чата из `.env`
    (`TELEGRAM_ADMIN_CHAT_ID`), который владелец узнаёт командой `/id` у бота.
    """
    rows = await session.execute(
        select(User.telegram_id).where(User.telegram_id.isnot(None), User.is_admin.is_(True))
    )
    chat_ids = [str(tid) for (tid,) in rows.all() if tid]
    fallback = (os.environ.get("TELEGRAM_ADMIN_CHAT_ID") or "").strip()
    if fallback and fallback not in chat_ids:
        chat_ids.append(fallback)
    return chat_ids


def draft_keyboard(post_id: int) -> list:
    """Кнопки карантина: опубликовать, отклонить, отложить на два часа."""
    return [
        [
            {"text": "Опубликовать", "callback_data": f"post:publish:{post_id}"},
            {"text": "Отклонить", "callback_data": f"post:reject:{post_id}"},
            {"text": "Отложить 2 ч", "callback_data": f"post:later:{post_id}"},
        ]
    ]


async def get_autopost(session: AsyncSession) -> TelegramAutopost:
    """Настройки автопостинга: строка одна, создаём при первом обращении."""
    row = (
        await session.execute(select(TelegramAutopost).where(TelegramAutopost.id == 1))
    ).scalar_one_or_none()
    if row is None:
        row = TelegramAutopost(id=1)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


def is_quiet_now(row: TelegramAutopost) -> bool:
    """Ночь по МСК: не постим — канал не должен «пиликать» под утро."""
    hour = (datetime.utcnow() + timedelta(hours=3)).hour
    start, end = row.quiet_from, row.quiet_to
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


async def published_last_day(session: AsyncSession) -> int:
    """Сколько постов ушло в канал за сутки — для лимита автопостинга."""
    since = datetime.utcnow() - timedelta(days=1)
    total = (
        await session.execute(
            select(func.count())
            .select_from(TelegramPost)
            .where(TelegramPost.status == "published", TelegramPost.published_at >= since)
        )
    ).scalar()
    return int(total or 0)


async def autopost_allowed(session: AsyncSession, row: TelegramAutopost) -> tuple[bool, str]:
    """Можно ли сейчас собрать автопост: включён, не ночь, лимит не исчерпан."""
    if not row.enabled:
        return False, "автопостинг выключен"
    if is_quiet_now(row):
        return False, "окно тишины"
    if await published_last_day(session) >= max(1, row.posts_per_day):
        return False, "лимит на сутки исчерпан"
    return True, ""


async def make_draft(
    session: AsyncSession,
    s3: S3Storage,
    *,
    period: Optional[str] = None,
    board: Optional[str] = None,
    actor: str = "autopost",
) -> TelegramPost:
    """Собирает черновик дайджеста и отправляет его админам в ЛС (карантин).

    В канал ничего не уходит: админ получает картинку и текст в личку бота с
    кнопками «Опубликовать / Отклонить / Отложить».
    """
    row = await get_autopost(session)
    period = period or row.period or "day"
    items = await digest_media(session, period=period, board=board)
    boards = await board_slugs(session, items)
    caption = caption_for(kind="digest", boards=boards, total=len(items), period=period)
    label, url = button_for(None, None)

    post = build_post(
        kind="digest",
        caption=caption,
        media_ids=[item.id for item in items],
        image_mode="mosaic",
        button_text=label,
        button_url=url,
        actor=actor,
        status="draft",
    )
    session.add(post)
    await session.flush()   # id нужен для callback_data кнопок карантина

    image = await render_image(s3, items, "mosaic", max(0, min(24, row.blur)))
    buttons = draft_keyboard(int(post.id))
    delivered = 0
    for chat_id in await admin_chat_ids(session):
        try:
            if image:
                await telegram_api.send_photo(
                    photo=image, caption=caption, chat_id=chat_id, buttons=buttons
                )
            else:
                await telegram_api.send_message(text=caption, chat_id=chat_id, buttons=buttons)
            delivered += 1
        except Exception as exc:  # noqa: BLE001 — карантин не должен ломать воркер
            print(f"   [tg] карантин не доставлен в {chat_id}: {exc}")

    if delivered == 0:
        post.error = "Черновик создан, но админам не доставлен: никто не запускал бота"
    row.last_check_at = datetime.utcnow()
    await record_audit(
        session,
        action="telegram.draft",
        target=str(post.id),
        details=f"карантин: доставлено {delivered}",
    )
    await session.commit()
    await session.refresh(post)
    return post


# ── Розыгрыши ────────────────────────────────────────────────────────

async def active_giveaway(session: AsyncSession) -> Optional[Giveaway]:
    """Текущий розыгрыш, в который можно вступить."""
    return (
        await session.execute(
            select(Giveaway)
            .where(
                Giveaway.status.in_(("announced", "draft")),
                Giveaway.ends_at > datetime.utcnow(),
            )
            .order_by(Giveaway.ends_at)
            .limit(1)
        )
    ).scalar_one_or_none()


async def create_giveaway(
    session: AsyncSession,
    *,
    kind: str = "daily",
    prize_days: int = 3,
    title: str = "",
    hours: Optional[int] = None,
) -> Giveaway:
    """Создаёт розыгрыш: суточный (daily) или недельный (weekly)."""
    now = datetime.utcnow()
    span = timedelta(hours=hours) if hours else timedelta(days=7 if kind == "weekly" else 1)
    item = Giveaway(
        kind=kind if kind in ("daily", "weekly") else "daily",
        prize_days=max(1, min(30, prize_days)),
        title=(title or ("Розыгрыш недели" if kind == "weekly" else "Розыгрыш дня"))[:120],
        starts_at=now,
        ends_at=now + span,
        status="draft",
        created_by="admin-token",
    )
    session.add(item)
    await record_audit(
        session, action="giveaway.create", target="—", details=f"{item.kind}: {item.prize_days} дн."
    )
    await session.commit()
    await session.refresh(item)
    return item


async def join_giveaway(session: AsyncSession, user: User) -> tuple[Optional[Giveaway], bool]:
    """Записывает пользователя в активный розыгрыш: один аккаунт — одно участие."""
    giveaway = await active_giveaway(session)
    if giveaway is None:
        return None, False

    exists = (
        await session.execute(
            select(GiveawayEntry.id).where(
                GiveawayEntry.giveaway_id == giveaway.id, GiveawayEntry.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if exists:
        return giveaway, True

    session.add(
        GiveawayEntry(giveaway_id=giveaway.id, user_id=user.id, telegram_id=user.telegram_id)
    )
    await session.commit()
    return giveaway, False


async def giveaways_to_draw(session: AsyncSession) -> List[Giveaway]:
    """Розыгрыши, у которых истёк срок, а победители ещё не выбраны."""
    rows = await session.execute(
        select(Giveaway).where(
            Giveaway.status == "announced", Giveaway.ends_at <= datetime.utcnow()
        )
    )
    return list(rows.scalars().all())


async def draw_winners(session: AsyncSession, giveaway: Giveaway, *, count: int = 1) -> List[dict]:
    """Выбирает победителей и сразу выдаёт премиум (продлеваем `premium_until`)."""
    rows = await session.execute(
        select(GiveawayEntry, User)
        .join(User, User.id == GiveawayEntry.user_id)
        .where(GiveawayEntry.giveaway_id == giveaway.id)
    )
    entries = rows.all()
    winners: List[dict] = []

    if entries:
        now = datetime.utcnow()
        for entry, user in random.sample(entries, k=min(count, len(entries))):
            base = user.premium_until if user.premium_until and user.premium_until > now else now
            user.premium_until = base + timedelta(days=giveaway.prize_days)
            winners.append(
                {
                    "user_id": user.id,
                    "telegram_id": user.telegram_id,
                    "username": user.telegram_username or user.email,
                    "until": user.premium_until.isoformat(),
                }
            )

    giveaway.winners = winners
    giveaway.status = "drawn"
    await record_audit(
        session,
        action="giveaway.draw",
        target=str(giveaway.id),
        details=f"победителей: {len(winners)}, приз {giveaway.prize_days} дн.",
    )
    await session.commit()
    await session.refresh(giveaway)
    return winners


async def announce_giveaway(session: AsyncSession, giveaway: Giveaway) -> TelegramPost:
    """Пост-анонс розыгрыша с кнопкой «Участвовать» (deep-link в бота)."""
    url = telegram_publisher.bot_url(settings.TELEGRAM_BOT_USERNAME, f"giveaway_{giveaway.id}")
    text = (
        f"<b>{giveaway.title}</b>\n\n"
        f"Разыгрываем {giveaway.prize_days} дн. премиум-подписки.\n"
        f"Условие: подписка на канал и кнопка «Участвовать».\n"
        f"Итоги: {giveaway.ends_at:%d.%m %H:%M} UTC"
    )
    result = await telegram_api.send_message(
        text=text,
        chat_id=telegram_api.channel_chat_id(),
        buttons=[[{"text": "Участвовать", "url": url}]],
    )

    post = build_post(
        kind="announce",
        caption=text,
        media_ids=[],
        image_mode="none",
        button_text="Участвовать",
        button_url=url,
        actor="admin-token",
        status="published",
    )
    post.message_id = result.get("message_id")
    post.published_at = datetime.utcnow()
    session.add(post)

    giveaway.announce_message_id = result.get("message_id")
    giveaway.status = "announced"
    await record_audit(
        session, action="giveaway.announce", target=str(giveaway.id), details="анонс в канале"
    )
    await session.commit()
    await session.refresh(post)
    await session.refresh(giveaway)
    return post


async def publish_giveaway_results(session: AsyncSession, giveaway: Giveaway) -> TelegramPost:
    """Пост-итоги: победители и выданный приз."""
    winners = giveaway.winners or []
    if winners:
        lines = "\n".join(f"• {item.get('username') or item.get('telegram_id')}" for item in winners)
        text = (
            f"<b>{giveaway.title}: итоги</b>\n\n"
            f"Победители:\n{lines}\n\n"
            f"Премиум на {giveaway.prize_days} дн. уже выдан."
        )
    else:
        text = f"<b>{giveaway.title}: итоги</b>\n\nЖелающих не нашлось — розыгрыш без победителя."

    result = await telegram_api.send_message(text=text, chat_id=telegram_api.channel_chat_id())
    post = build_post(
        kind="announce",
        caption=text,
        media_ids=[],
        image_mode="none",
        button_text="",
        button_url="",
        actor="admin-token",
        status="published",
    )
    post.message_id = result.get("message_id")
    post.published_at = datetime.utcnow()
    session.add(post)

    giveaway.result_message_id = result.get("message_id")
    await record_audit(
        session, action="giveaway.results", target=str(giveaway.id), details="итоги в канале"
    )
    await session.commit()
    await session.refresh(post)
    await session.refresh(giveaway)
    return post





