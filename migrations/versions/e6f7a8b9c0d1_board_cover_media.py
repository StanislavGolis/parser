"""Ручные превью карточки раздела: boards.cover_media_ids.

Каталог разделов собирал мозаику 2×2 автоматически из четырёх свежих файлов, и
админ не мог повлиять на то, как выглядит раздел в каталоге. Теперь выбор можно
закрепить вручную: `boards.cover_media_ids` хранит id файлов этого раздела в
нужном порядке (до 4). NULL — как раньше, автоматический выбор.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-14 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "boards",
        sa.Column("cover_media_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("boards", "cover_media_ids")
