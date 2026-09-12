"""объединение метки и избранного: favorites → media_marks

Revision ID: p1q2r3s4t5u6
Revises: o0p1q2r3s4t5
Create Date: 2026-09-13 05:20:00.000000

Раньше были две пользовательские сущности: «метка» (`media_marks`, публичный
счётчик и рейтинг) и «избранное» (`favorites`, личный список). Оставляем одну —
**метку**: личный список теперь это «мои метки».

Миграция переносит избранное в метки (без дублей), пересчитывает
`media.marks_count` и удаляет таблицу `favorites`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'p1q2r3s4t5u6'
down_revision: Union[str, None] = 'o0p1q2r3s4t5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Переносим избранное в метки (у кого метка уже стояла — не дублируем)
    op.execute(
        """
        INSERT INTO media_marks (user_id, media_id, created_at)
        SELECT f.user_id, f.media_id, f.created_at
        FROM favorites f
        WHERE NOT EXISTS (
            SELECT 1 FROM media_marks m
            WHERE m.user_id = f.user_id AND m.media_id = f.media_id
        )
        """
    )

    # 2) Пересчитываем денормализованный счётчик меток по фактическим данным
    op.execute(
        """
        UPDATE media SET marks_count = COALESCE(
            (SELECT count(*) FROM media_marks m WHERE m.media_id = media.id), 0
        )
        """
    )

    # 3) Убираем «избранное» как отдельную сущность
    op.drop_index('ix_favorites_media', table_name='favorites')
    op.drop_index('ix_favorites_user_id', table_name='favorites')
    op.drop_table('favorites')


def downgrade() -> None:
    # Данные избранного после объединения восстановить нельзя (они теперь метки),
    # поэтому возвращаем только пустую таблицу — для отката схемы.
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
