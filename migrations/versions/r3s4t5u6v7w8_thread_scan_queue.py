"""очередь докачки тредов: pending_scan / pending_reason / last_scan_attempt_at

Revision ID: r3s4t5u6v7w8
Revises: q2r3s4t5u6v7
Create Date: 2026-09-12 13:20:00.000000

Раньше цикл был «по доске за раз»: каталог → сразу все изменённые треды,
и только после этого следующая доска. Большой тред (сотни файлов) откладывал
все остальные доски на часы, а при перезапуске процесс начинал с начала.

Теперь цикл двухфазный:
* фаза A (`sync_board_catalog`) — дёшево обходит каталоги всех досок
  (1 запрос на доску) и помечает треды `pending_scan` с причиной;
* фаза B (`scan_thread`) — докачивает файлы по очереди из БД.

Очередь живёт в БД, поэтому перезапуск процесса её не теряет, а порядок
(свежие изменения → давно не сканировавшиеся) задаёт `last_scanned_at`.
`last_scan_attempt_at` — время последней попытки (диагностика в админке).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'r3s4t5u6v7w8'
down_revision: Union[str, None] = 'q2r3s4t5u6v7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'threads_state',
        sa.Column('pending_scan', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'threads_state',
        sa.Column('pending_reason', sa.String(length=32), nullable=True),
    )
    op.add_column(
        'threads_state',
        sa.Column('last_scan_attempt_at', sa.DateTime(), nullable=True),
    )

    # Треды «в работе» попадают в очередь один раз: уже скачанные отсеются по
    # md5 без повторного скачивания, зато ни один тред не будет пропущен после
    # переключения на двухфазный цикл.
    op.execute(
        """
        UPDATE threads_state
        SET pending_scan = TRUE,
            pending_reason = CASE
                WHEN last_scanned_at IS NULL THEN 'не скачивался'
                ELSE 'просрочен'
            END
        WHERE parse_enabled IS TRUE AND is_active IS TRUE
        """
    )

    # Индекс под выборку очереди (фаза B) и под счётчики админки.
    op.create_index(
        'ix_threads_state_scan_queue',
        'threads_state',
        ['pending_scan', 'parse_enabled', 'is_active', 'last_scanned_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_threads_state_scan_queue', table_name='threads_state')
    op.drop_column('threads_state', 'last_scan_attempt_at')
    op.drop_column('threads_state', 'pending_reason')
    op.drop_column('threads_state', 'pending_scan')
