"""media.variants (thumb/web) + duration_seconds: оптимизация трафика

Revision ID: k6l7m8n9o0p1
Revises: j5k6l7m8n9o0
Create Date: 2026-09-12 20:00:00.000000

variants: {"thumb": "<s3_key>", "web": "<s3_key>"} — превью и оптимизированная
версия файла (WebP для фото, poster/720p для видео).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'k6l7m8n9o0p1'
down_revision: Union[str, None] = 'j5k6l7m8n9o0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('media', sa.Column('variants', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('media', sa.Column('duration_seconds', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('media', 'duration_seconds')
    op.drop_column('media', 'variants')
