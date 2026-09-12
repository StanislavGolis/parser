"""инкрементальный проход и итог скана: last_post_num / last_scan_errors / last_scan_note

Revision ID: s4t5u6v7w8x9
Revises: r3s4t5u6v7w8
Create Date: 2026-09-12 14:40:00.000000

1) `last_post_num` — номер последнего поста, полностью обработанного «чистым»
   проходом. Частые сканы по причине «изменения» смотрят только посты новее —
   горячие треды (сотни файлов) не перебираются целиком каждый раз. Плановый
   догон («просрочен»), «недокачано», «вручную» и первый проход идут полным
   обходом, поэтому неудавшиеся загрузки повторяются, а правки старых постов
   подхватываются.

2) `last_scan_errors` — сколько файлов упало в последнем проходе: если больше нуля,
   следующий проход принудительно полный (перепроверить проблемные файлы).

3) `last_scan_note` — человеческий итог последнего прохода для админки
   («новых 12, уже было 319, дублей 3, битых 5, отфильтровано 24, ошибок 1»),
   чтобы разбор недокачки не требовал чтения логов.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 's4t5u6v7w8x9'
down_revision: Union[str, None] = 'r3s4t5u6v7w8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'threads_state',
        sa.Column('last_post_num', sa.Integer(), nullable=True),
    )
    op.add_column(
        'threads_state',
        sa.Column('last_scan_errors', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'threads_state',
        sa.Column('last_scan_note', sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('threads_state', 'last_scan_note')
    op.drop_column('threads_state', 'last_scan_errors')
    op.drop_column('threads_state', 'last_post_num')
