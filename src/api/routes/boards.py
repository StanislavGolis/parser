# src/api/routes/boards.py
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import access_cookie_name, board_access_granted, hash_access_code
from src.api.deps import check_rate_limit, client_ip, get_s3
from src.api.schemas import AccessRequest, AccessResult, BoardOut, ThreadListOut
from src.api.threads_service import build_thread_outs, list_threads
from src.core.db import get_session
from src.core.models import Board, Media
from src.services.s3_storage import S3Storage

router = APIRouter(prefix="/api/v1/boards", tags=["boards"])

ACCESS_COOKIE_MAX_AGE = 24 * 60 * 60


@router.get("", response_model=list[BoardOut])
async def list_boards(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Список видимых досок (включая приватные) с числом видимых файлов.

    Приватные доски видны в списке, но их контент открывается только по коду.
    """
    await check_rate_limit(client_ip(request))

    subq = (
        select(
            Media.board_id.label("board_id"),
            func.count(Media.id).label("cnt"),
        )
        .where(Media.is_visible.is_(True), Media.is_active.is_(True))
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

    boards = []
    for board, cnt in result.all():
        boards.append(BoardOut(
            id=board.id,
            slug=board.slug,
            title=board.title,
            description=board.description,
            media_count=int(cnt or 0),
            is_private=board.is_private,
        ))
    return boards


@router.get("/{slug}/threads", response_model=ThreadListOut)
async def board_threads(
    slug: str,
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
):
    """Треды доски (активные) с метаданными и статистикой файлов.

    Приватная доска доступна только с валидным cookie кода.
    """
    await check_rate_limit(client_ip(request))

    result = await session.execute(
        select(Board).where(Board.slug == slug, Board.is_visible.is_(True))
    )
    board = result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    if board.is_private and not board_access_granted(request, board):
        raise HTTPException(status_code=403, detail="Access denied")

    threads, total = await list_threads(session, board.id, page, per_page)
    items = await build_thread_outs(session, board.id, threads, s3=s3, with_preview=True)
    return ThreadListOut(items=items, page=page, per_page=per_page, total=total)


@router.post("/{slug}/access", response_model=AccessResult)
async def board_access(
    slug: str,
    payload: AccessRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """Проверка кода доступа к приватной доске.

    При успехе выставляет httpOnly-cookie ba_{slug} (sha256 кода) на 24 часа.
    """
    await check_rate_limit(client_ip(request))

    result = await session.execute(
        select(Board).where(Board.slug == slug, Board.is_visible.is_(True))
    )
    board = result.scalar_one_or_none()
    if not board or not board.is_private:
        raise HTTPException(status_code=404, detail="Board not found")

    code = (payload.code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Code is empty")

    code_hash = hash_access_code(code)
    if not board.access_code_hash or code_hash != board.access_code_hash:
        raise HTTPException(status_code=403, detail="Access denied")

    response.set_cookie(
        key=access_cookie_name(board.slug),
        value=code_hash,
        max_age=ACCESS_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return AccessResult(granted=True)