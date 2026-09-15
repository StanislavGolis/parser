# src/api/routes/boards.py
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import (
    VISIBLE_FILTER,
    asset_url,
    is_locked,
    visible_thread_clause,
)
from src.api.deps import check_rate_limit, client_ip, get_current_user, get_s3
from src.api.schemas import BoardOut, ThreadListOut
from src.api.threads_service import build_thread_outs, list_threads
from src.core.db import get_session
from src.core.models import Board, Media, User
from src.services import reporting
from src.services.s3_storage import S3Storage

router = APIRouter(prefix="/api/v1/boards", tags=["boards"])

# Сколько превью показываем на карточке раздела (мозаика 2×2).
COVER_THUMBS = 4


async def _cover_thumbs(
    session: AsyncSession,
    boards: list[Board],
    locked_board_ids: set[int],
) -> dict[int, list[str]]:
    """Превью разделов для каталога — одним запросом на весь список.

    Ручной выбор приоритетнее: если админ отметил файлы (`boards.cover_media_ids`),
    они занимают первые плитки и в том же порядке. Если выбрано меньше четырёх,
    свободные плитки добираются свежими файлами раздела (иначе в каталоге были бы
    пустые квадраты). Полностью автоматический режим — четыре свежих файла.
    Для закрытых премиум-разделов отдаём размытые варианты (как и в других
    списках): превью не раскрывает содержимое без подписки.
    """
    covers: dict[int, list[str]] = {}
    if not boards:
        return covers

    used: dict[int, set[int]] = {}

    def add(board_id: int, media_id: int, variants: Optional[dict]) -> None:
        taken = used.setdefault(board_id, set())
        # Не больше четырёх плиток и без повторов (выбранное вручную не дублируем)
        if media_id in taken or len(taken) >= COVER_THUMBS:
            return
        variants = variants or {}
        if board_id in locked_board_ids:
            blur = variants.get("thumb_blur")
            if not blur:
                return
            url = asset_url(media_id, "thumb_blur", blur)
        else:
            thumb = variants.get("thumb")
            if not thumb:
                return
            url = asset_url(media_id, "thumb", thumb)
        taken.add(media_id)
        covers.setdefault(board_id, []).append(url)

    # 1) Разделы с ручным выбором: порядок = порядок выбранных id
    manual = {
        b.id: [mid for mid in (b.cover_media_ids or [])][:COVER_THUMBS]
        for b in boards
        if b.cover_media_ids
    }
    if manual:
        wanted = [mid for ids in manual.values() for mid in ids]
        rows = await session.execute(
            select(Media.id, Media.board_id, Media.variants).where(
                *VISIBLE_FILTER, visible_thread_clause(), Media.id.in_(wanted)
            )
        )
        found = {row.id: row for row in rows.all()}
        for board_id, ids in manual.items():
            for media_id in ids:
                row = found.get(media_id)
                # Файл мог быть скрыт или перенесён в другой раздел — пропускаем
                if row is not None and row.board_id == board_id:
                    add(board_id, row.id, row.variants)

    # 2) Остальные плитки: 4 самых свежих файла (для частично выбранных — добор)
    auto_ids = [
        b.id for b in boards if len(used.get(b.id, ())) < COVER_THUMBS
    ]
    if not auto_ids:
        return covers

    row_number = (
        func.row_number()
        .over(
            partition_by=Media.board_id,
            order_by=(Media.created_at.desc(), Media.id.desc()),
        )
        .label("rn")
    )
    ranked = (
        select(Media.id, Media.board_id, Media.variants, row_number)
        .where(*VISIBLE_FILTER, visible_thread_clause(), Media.board_id.in_(auto_ids))
        .subquery()
    )
    rows = await session.execute(
        select(ranked.c.board_id, ranked.c.id, ranked.c.variants)
        .where(ranked.c.rn <= COVER_THUMBS)
        .order_by(ranked.c.board_id, ranked.c.rn)
    )
    for board_id, media_id, variants in rows.all():
        add(board_id, media_id, variants)
    return covers


@router.get("", response_model=list[BoardOut])
async def list_boards(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: Optional[User] = Depends(get_current_user),
):
    """Список видимых досок с числом видимых файлов.

    Премиум-доски видны в списке: их контент открывается по подписке
    (`locked=true`, если подписки у зрителя нет).
    """
    await check_rate_limit(client_ip(request))

    subq = (
        select(
            Media.board_id.label("board_id"),
            func.count(Media.id).label("cnt"),
        )
        .where(
            Media.is_visible.is_(True),
            Media.is_active.is_(True),
            # Дубли-ссылки не файлы: в каталоге считаем только уникальные
            Media.duplicate_of_id.is_(None),
        )
        .group_by(Media.board_id)
        .subquery()
    )

    query = (
        select(Board, func.coalesce(subq.c.cnt, 0))
        .outerjoin(subq, subq.c.board_id == Board.id)
        .where(Board.is_visible.is_(True))
        .order_by(Board.slug)
    )
    result = await session.execute(query)
    rows = result.all()

    locked_ids = {
        board.id for board, _cnt in rows if is_locked(board.is_premium, user)
    }
    covers = await _cover_thumbs(session, [board for board, _cnt in rows], locked_ids)
    # «+N за сегодня» — прирост за текущие отчётные сутки (МСК): тем же периодом
    # считают главная, админка и письмо-отчёт, поэтому цифры не расходятся
    start, end = reporting.period_bounds()
    today = await reporting.media_today_by_board(session, start, end)

    boards = []
    for board, cnt in rows:
        boards.append(BoardOut(
            id=board.id,
            slug=board.slug,
            title=board.title,
            description=board.description,
            media_count=int(cnt or 0),
            media_today=int(today.get(board.id, 0)),
            is_premium=board.is_premium,
            locked=is_locked(board.is_premium, user),
            cover_thumbs=covers.get(board.id, []),
        ))
    return boards


@router.get("/{slug}/threads", response_model=ThreadListOut)
async def board_threads(
    slug: str,
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=50),
    sort: str = Query(
        "new",
        pattern="^(new|files|posts|views)$",
        description=(
            "Порядок тредов: `new` — свежие, `files` — больше файлов в архиве, "
            "`posts` — больше постов, `views` — больше просмотров"
        ),
    ),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
    user: Optional[User] = Depends(get_current_user),
):
    """Треды доски (активные) с метаданными и статистикой файлов.

    Превью премиум-тредов приходят размытыми; полный контент — по подписке.
    """
    await check_rate_limit(client_ip(request))

    result = await session.execute(
        select(Board).where(Board.slug == slug, Board.is_visible.is_(True))
    )
    board = result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    threads, total = await list_threads(
        session, board.id, page, per_page, only_visible=True, sort=sort
    )
    items = await build_thread_outs(
        session,
        board.id,
        threads,
        s3=s3,
        with_preview=True,
        user=user,
        board_premium=board.is_premium,
    )
    return ThreadListOut(items=items, page=page, per_page=per_page, total=total)
