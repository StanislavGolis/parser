# src/api/routes/admin.py
"""Админ-эндпоинты (защищены ADMIN_TOKEN): управление досками и файлами."""
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import hash_access_code
from src.api.deps import verify_admin
from src.api.schemas import (
    AdminBoardOut,
    BoardCreate,
    BoardUpdate,
    ToggleResult,
)
from src.core.db import get_session
from src.core.models import Board, Media

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

SLUG_RE = re.compile(r"^[a-z0-9]{1,32}$")


def _media_counts_subq():
    """Число видимых активных файлов по доскам (для ответа админке)."""
    return (
        select(
            Media.board_id.label("board_id"),
            func.count(Media.id).label("cnt"),
        )
        .where(Media.is_visible.is_(True), Media.is_active.is_(True))
        .group_by(Media.board_id)
        .subquery()
    )


async def _load_board(session: AsyncSession, slug: str) -> Board:
    result = await session.execute(select(Board).where(Board.slug == slug))
    board = result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    return board


@router.get("/boards", response_model=list[AdminBoardOut])
async def list_admin_boards(
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Все доски (включая скрытые) с флагами управления."""
    subq = _media_counts_subq()
    query = (
        select(Board, func.coalesce(subq.c.cnt, 0))
        .outerjoin(subq, subq.c.board_id == Board.id)
        .order_by(Board.slug)
    )
    result = await session.execute(query)

    boards = []
    for board, cnt in result.all():
        boards.append(AdminBoardOut(
            id=board.id,
            slug=board.slug,
            title=board.title,
            description=board.description,
            media_count=int(cnt or 0),
            is_visible=board.is_visible,
            is_private=board.is_private,
            parse_enabled=board.parse_enabled,
            has_access_code=bool(board.access_code_hash),
        ))
    return boards


@router.post("/boards", response_model=AdminBoardOut)
async def create_board(
    payload: BoardCreate,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Создаёт доску по слагу (например, которой ещё нет в БД)."""
    slug = (payload.slug or "").strip().lower()
    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="Invalid slug (a-z0-9, до 32 символов)")

    existing = await session.execute(select(Board).where(Board.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Board already exists")

    board = Board(slug=slug, title=slug, parse_enabled=False, is_visible=False)
    session.add(board)
    await session.commit()
    await session.refresh(board)
    return AdminBoardOut(
        id=board.id, slug=board.slug, title=board.title, description=None,
        media_count=0, is_visible=False, is_private=False,
        parse_enabled=False, has_access_code=False,
    )


@router.patch("/boards/{slug}", response_model=AdminBoardOut)
async def update_board(
    slug: str,
    payload: BoardUpdate,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Обновляет флаги доски и/или код доступа.

    access_code: непустая строка — установить/сменить код;
    пустая строка — сбросить код (закроет приватный доступ).
    """
    board = await _load_board(session, slug)

    if payload.parse_enabled is not None:
        board.parse_enabled = payload.parse_enabled
    if payload.is_visible is not None:
        board.is_visible = payload.is_visible
    if payload.is_private is not None:
        board.is_private = payload.is_private

    if payload.access_code is not None:
        code = payload.access_code.strip()
        if code:
            board.access_code_hash = hash_access_code(code)
        else:
            # Явный сброс кода
            board.access_code_hash = None

    if board.is_private and not board.access_code_hash:
        raise HTTPException(
            status_code=400,
            detail="Для приватной доски нужно задать код доступа",
        )

    await session.commit()

    cnt = (
        await session.execute(
            select(func.count()).select_from(Media).where(
                Media.board_id == board.id,
                Media.is_visible.is_(True),
                Media.is_active.is_(True),
            )
        )
    ).scalar()

    return AdminBoardOut(
        id=board.id,
        slug=board.slug,
        title=board.title,
        description=board.description,
        media_count=int(cnt or 0),
        is_visible=board.is_visible,
        is_private=board.is_private,
        parse_enabled=board.parse_enabled,
        has_access_code=bool(board.access_code_hash),
    )


@router.post("/boards/{slug}/toggle", response_model=ToggleResult)
async def toggle_board(
    slug: str,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Скрыть/показать доску (обратная совместимость)."""
    board = await _load_board(session, slug)
    board.is_visible = not board.is_visible
    await session.commit()
    return ToggleResult(id=board.id, is_visible=board.is_visible)


@router.post("/media/{media_id}/toggle", response_model=ToggleResult)
async def toggle_media(
    media_id: int,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Скрыть/показать файл."""
    media = await session.get(Media, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    media.is_visible = not media.is_visible
    await session.commit()
    return ToggleResult(id=media.id, is_visible=media.is_visible)