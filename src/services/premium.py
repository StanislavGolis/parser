# src/services/premium.py
"""Премиум-доступ: статус пользователя и синхронизация признака media.is_premium.

Модель: премиум задаётся флагом у доски и/или у треда; если доска премиальная —
премиальными считаются все её треды (эффективный премиум = доска ИЛИ тред).

Признак дублируется на `media.is_premium`, чтобы публичные выборки
(лента/топ/поиск/галерея/превью тредов) блюрили превью и не отдавали полный
контент без лишних JOIN'ов. Синхронизация вызывается из админки при смене
флагов, а новые файлы парсер пишет сразу с нужным значением.
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import Board, Media, ThreadState, User

# Промо-период: сколько дней премиума выдаём бесплатно по кнопке в профиле
PROMO_PREMIUM_DAYS = 1


def premium_active(user: Optional[User], now: Optional[datetime] = None) -> bool:
    """Действует ли у пользователя премиум-статус прямо сейчас."""
    if user is None or user.premium_until is None:
        return False
    return user.premium_until > (now or datetime.utcnow())


def grant_premium(user: User, days: int = PROMO_PREMIUM_DAYS) -> datetime:
    """Продлевает премиум на `days` дней (от текущего срока или от сейчас)."""
    now = datetime.utcnow()
    base = user.premium_until if (user.premium_until and user.premium_until > now) else now
    user.premium_until = base + timedelta(days=days)
    return user.premium_until


async def sync_board_media_premium(session: AsyncSession, board: Board) -> None:
    """Пересчитывает признак премиума у всех файлов доски.

    Вызывается при смене board.is_premium: включение закрывает весь контент
    доски, выключение оставляет премиум только у файлов премиум-тредов.
    """
    if board.is_premium:
        await session.execute(
            update(Media).where(Media.board_id == board.id).values(is_premium=True)
        )
        return

    await session.execute(
        update(Media).where(Media.board_id == board.id).values(is_premium=False)
    )
    premium_threads = select(ThreadState.thread_id).where(
        ThreadState.board_id == board.id,
        ThreadState.is_premium.is_(True),
    )
    await session.execute(
        update(Media)
        .where(Media.board_id == board.id, Media.thread_id.in_(premium_threads))
        .values(is_premium=True)
    )


async def sync_thread_media_premium(
    session: AsyncSession, board: Board, thread: ThreadState
) -> None:
    """Пересчитывает признак премиума у файлов одного треда.

    Если премиум включён на доске, тред остаётся закрытым и при is_premium=False.
    """
    value = bool(board.is_premium or thread.is_premium)
    await session.execute(
        update(Media)
        .where(Media.board_id == board.id, Media.thread_id == thread.thread_id)
        .values(is_premium=value)
    )


async def sync_threads_media_premium(
    session: AsyncSession, board: Board, thread_ids
) -> None:
    """Пересчитывает премиум у файлов нескольких тредов (массовая правка)."""
    thread_ids = list(thread_ids)
    if not thread_ids:
        return
    if board.is_premium:
        await session.execute(
            update(Media)
            .where(Media.board_id == board.id, Media.thread_id.in_(thread_ids))
            .values(is_premium=True)
        )
        return

    await session.execute(
        update(Media)
        .where(Media.board_id == board.id, Media.thread_id.in_(thread_ids))
        .values(is_premium=False)
    )
    premium_threads = select(ThreadState.thread_id).where(
        ThreadState.board_id == board.id,
        ThreadState.thread_id.in_(thread_ids),
        ThreadState.is_premium.is_(True),
    )
    await session.execute(
        update(Media)
        .where(Media.board_id == board.id, Media.thread_id.in_(premium_threads))
        .values(is_premium=True)
    )
