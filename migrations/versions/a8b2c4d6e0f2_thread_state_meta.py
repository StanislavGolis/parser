"""threads_state: subject/comment/thread_timestamp для списка тредов

Revision ID: a8b2c4d6e0f2
Revises: e7f3a1c9b2d4
Create Date: 2026-09-06 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8b2c4d6e0f2'
down_revision: Union[str, None] = 'e7f3a1c9b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('threads_state', sa.Column('subject', sa.String(length=500), nullable=True))
    op.add_column('threads_state', sa.Column('comment', sa.Text(), nullable=True))
    op.add_column('threads_state', sa.Column('thread_timestamp', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('threads_state', 'thread_timestamp')
    op.drop_column('threads_state', 'comment')
    op.drop_column('threads_state', 'subject')