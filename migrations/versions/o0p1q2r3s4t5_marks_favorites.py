"""marks и favorites: метки (аналог лайка) и избранное + media.marks_count

Revision ID: o0p1q2r3s4t5
Revises: n9o0p1q2r3s4
Create Date: 2026-09-13 04:10:00.000000

Пользовательские действия, требующие аккаунта:
- `media_marks` — метки «отличный контент» (наш аналог лайка), переключатель;
- `favorites` — личное избранное;
- `media.marks_count` — денормализованный счётчик меток (для карточек и сортировки).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'o0p1q2r3s4t5'
down_revision: Union[str, None] = 'n9o0p1q2r3s4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'media',
        sa.Column('marks_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
    )

    op.create_table(
        'media_marks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('media_id', sa.Integer(), sa.ForeignKey('media.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('user_id', 'media_id', name='uq_media_marks_user_media'),
    )
    op.create_index('ix_media_marks_user_id', 'media_marks', ['user_id'])
    op.create_index('ix_media_marks_media', 'media_marks', ['media_id'])

    op.create_table(
        'favorites',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('media_id', sa.Integer(), sa.ForeignKey('media.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('user_id', 'media_id', name='uq_favorites_user_media'),
    )
    op.create_index('ix_favorites_user_id', 'favorites', ['user_id'])
    op.create_index('ix_favorites_media', 'favorites', ['media_id'])


def downgrade() -> None:
    op.drop_index('ix_favorites_media', table_name='favorites')
    op.drop_index('ix_favorites_user_id', table_name='favorites')
    op.drop_table('favorites')
    op.drop_index('ix_media_marks_media', table_name='media_marks')
    op.drop_index('ix_media_marks_user_id', table_name='media_marks')
    op.drop_table('media_marks')
    op.drop_column('media', 'marks_count')
