"""defaults: новые доски и треды выключены (не парсить / не показывать)

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-09-12 14:00:00.000000

Меняем только server_default для новых строк; существующие данные не трогаем.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h3i4j5k6l7m8'
down_revision: Union[str, None] = 'g2h3i4j5k6l7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('boards', 'parse_enabled', server_default=sa.text('false'))
    op.alter_column('boards', 'is_visible', server_default=sa.text('false'))
    op.alter_column('boards', 'parse_mode', server_default=sa.text("'selected'"))
    op.alter_column('threads_state', 'parse_enabled', server_default=sa.text('false'))
    op.alter_column('threads_state', 'is_visible', server_default=sa.text('false'))


def downgrade() -> None:
    op.alter_column('boards', 'parse_enabled', server_default=sa.text('true'))
    op.alter_column('boards', 'is_visible', server_default=sa.text('true'))
    op.alter_column('boards', 'parse_mode', server_default=sa.text("'all'"))
    op.alter_column('threads_state', 'parse_enabled', server_default=sa.text('true'))
    op.alter_column('threads_state', 'is_visible', server_default=sa.text('true'))
