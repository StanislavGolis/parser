"""threads_state.fingerprint: отпечаток «треда» для источников без счётчиков

У сайтов-источников нет ни числа постов, ни числа файлов, поэтому планировщику
не с чем сравнивать состояние «треда». Адаптер отдаёт свою метку изменения
(например, имя обложки записи), планировщик её хранит и по ней ставит запись в
очередь, когда она обновилась.

Revision ID: x9y0z1a2b3c4
Revises: w8x9y0z1a2b3
Create Date: 2026-09-13 03:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'x9y0z1a2b3c4'
down_revision: Union[str, None] = 'w8x9y0z1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('threads_state', sa.Column('fingerprint', sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column('threads_state', 'fingerprint')
