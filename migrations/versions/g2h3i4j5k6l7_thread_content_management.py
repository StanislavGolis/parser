"""thread content management: boards.parse_mode + флаги тредов

Revision ID: g2h3i4j5k6l7
Revises: f1a2b3c4d5e6
Create Date: 2026-09-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g2h3i4j5k6l7'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Режим выбора тредов на доске: all (все) | selected (только выбранные)
    op.add_column('boards', sa.Column('parse_mode', sa.String(length=16), nullable=False, server_default=sa.text("'all'")))
    # Управление тредами из админки
    op.add_column('threads_state', sa.Column('parse_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('threads_state', sa.Column('is_visible', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('threads_state', sa.Column('is_private', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('threads_state', sa.Column('access_code_hash', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('threads_state', 'access_code_hash')
    op.drop_column('threads_state', 'is_private')
    op.drop_column('threads_state', 'is_visible')
    op.drop_column('threads_state', 'parse_enabled')
    op.drop_column('boards', 'parse_mode')
