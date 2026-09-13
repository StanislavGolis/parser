"""user_resume_points: точка возврата «продолжить просмотр» в БД

Раньше точка жила только в localStorage браузера: анониму этого достаточно, но
зарегистрированный зритель терял место при смене устройства. Новая таблица
хранит точку для аккаунта (ключ — пользователь + тред); localStorage остаётся
фолбэком и источником для анонимов.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-09-13 10:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_resume_points',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('thread_id', sa.Integer(), nullable=False),
        sa.Column('media_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'thread_id', name='uq_user_resume_user_thread'),
    )
    op.create_index('ix_user_resume_user_updated', 'user_resume_points', ['user_id', 'updated_at'])


def downgrade() -> None:
    op.drop_index('ix_user_resume_user_updated', table_name='user_resume_points')
    op.drop_table('user_resume_points')
