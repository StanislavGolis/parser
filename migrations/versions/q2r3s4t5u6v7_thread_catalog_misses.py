"""гигиена обхода тредов: промахи каталога и дата исчезновения

Revision ID: q2r3s4t5u6v7
Revises: p1q2r3s4t5u6
Create Date: 2026-09-12 12:10:00.000000

Парсер обходит треды по каталогу доски, поэтому тред, выпавший из каталога,
раньше молча гасился (`is_active=False`) с первого же промаха и после этого
становился невидимым в админке (списки и счётчики фильтровали `is_active`).

Добавляем два поля:
* `misses` — сколько проходов каталога подряд треда не было в каталоге;
* `missing_since` — момент, когда тред впервые пропал из каталога.

Тред выключается только после `DEAD_THREAD_AFTER_MISSES` промахов (случайный
обрыв каталога 2ch больше не гасит треды пачкой), а в админке появляются
фильтры «Мёртвые» и «Просроченные».
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'q2r3s4t5u6v7'
down_revision: Union[str, None] = 'p1q2r3s4t5u6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'threads_state',
        sa.Column('misses', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'threads_state',
        sa.Column('missing_since', sa.DateTime(), nullable=True),
    )

    # Ранее отключённые треды (is_active=False) появились из-за старой логики
    # «один промах = мёртв». Дату исчезновения точно не знаем — берём время
    # последнего успешного прохода как наиболее близкую оценку.
    op.execute(
        """
        UPDATE threads_state
        SET misses = 3,
            missing_since = COALESCE(last_scanned_at, now())
        WHERE is_active IS FALSE
        """
    )

    # Индекс под фильтры/счётчики админки: «просроченные» и «мёртвые».
    op.create_index(
        'ix_threads_state_board_active',
        'threads_state',
        ['board_id', 'is_active'],
    )


def downgrade() -> None:
    op.drop_index('ix_threads_state_board_active', table_name='threads_state')
    op.drop_column('threads_state', 'missing_since')
    op.drop_column('threads_state', 'misses')
