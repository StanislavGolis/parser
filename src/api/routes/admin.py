# src/api/routes/admin.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import verify_admin
from src.api.schemas import ToggleResult
from src.core.db import get_session
from src.core.models import Board, Media

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/boards/{slug}/toggle", response_model=ToggleResult)
async def toggle_board(
    slug: str,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Скрыть/показать доску."""
    result = await session.execute(select(Board).where(Board.slug == slug))
    board = result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
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