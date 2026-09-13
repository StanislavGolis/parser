"""обратная связь: таблица feedback (идеи, баги, запросы премиум-доступа)

Форма `/feedback` пишет обращение в БД и дублирует его письмом админам; в админке
заявки лежат в отдельной вкладке со статусами (new → in_progress → answered →
closed) и заметкой-ответом.

Revision ID: z1a2b3c4d5e6
Revises: y0z1a2b3c4d5
Create Date: 2026-09-13 06:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'z1a2b3c4d5e6'
down_revision: Union[str, None] = 'y0z1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('topic', sa.String(length=24), nullable=False, server_default='other'),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('page_url', sa.String(length=255), nullable=True),
        sa.Column('ip_hash', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='new'),
        sa.Column('admin_note', sa.Text(), nullable=True),
        sa.Column('answered_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_feedback_created_at', 'feedback', ['created_at'])
    op.create_index('ix_feedback_user_id', 'feedback', ['user_id'])
    op.create_index('ix_feedback_status_created', 'feedback', ['status', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_feedback_status_created', table_name='feedback')
    op.drop_index('ix_feedback_user_id', table_name='feedback')
    op.drop_index('ix_feedback_created_at', table_name='feedback')
    op.drop_table('feedback')
