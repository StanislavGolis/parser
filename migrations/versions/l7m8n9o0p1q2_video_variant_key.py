"""variants: видео-дериватив в ключ 'video' (для кэша nginx slice)

Revision ID: l7m8n9o0p1q2
Revises: k6l7m8n9o0p1
Create Date: 2026-09-12 22:00:00.000000

Видео-дериватив хранился под ключом 'web'; выделяем в 'video', чтобы у него
был отдельный URL (/asset/video) — только его nginx кэширует чанками (slice).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'l7m8n9o0p1q2'
down_revision: Union[str, None] = 'k6l7m8n9o0p1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE media
        SET variants = (variants - 'web') || jsonb_build_object('video', variants->'web')
        WHERE media_type = 'video' AND variants ? 'web'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE media
        SET variants = (variants - 'video') || jsonb_build_object('web', variants->'video')
        WHERE media_type = 'video' AND variants ? 'video'
        """
    )
