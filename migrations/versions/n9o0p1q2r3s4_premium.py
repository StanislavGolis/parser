"""premium-доступ: is_premium вместо кода; media.is_premium; users.premium_until

Revision ID: n9o0p1q2r3s4
Revises: m8n9o0p1q2r3
Create Date: 2026-09-13 01:30:00.000000

Заменяем доступ «по коду» на премиум-подписку:
- boards.is_premium / threads_state.is_premium (доска → все её треды);
- media.is_premium — денормализованный признак для простой отдачи/блюра;
- users.premium_until — срок действия премиума;
- колонки is_private/access_code_hash удаляются (данные переносятся).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'n9o0p1q2r3s4'
down_revision: Union[str, None] = 'm8n9o0p1q2r3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── boards ──────────────────────────────────────────────────
    op.add_column('boards', sa.Column('is_premium', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.execute("UPDATE boards SET is_premium = is_private")
    op.drop_column('boards', 'access_code_hash')
    op.drop_column('boards', 'is_private')

    # ── threads_state ───────────────────────────────────────────
    op.add_column('threads_state', sa.Column('is_premium', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.execute("UPDATE threads_state SET is_premium = is_private")
    op.drop_column('threads_state', 'access_code_hash')
    op.drop_column('threads_state', 'is_private')

    # ── media: денормализованный премиум (доска ИЛИ тред) ───────
    op.add_column('media', sa.Column('is_premium', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.execute(
        """
        UPDATE media m SET is_premium = true
        WHERE EXISTS (SELECT 1 FROM boards b WHERE b.id = m.board_id AND b.is_premium)
           OR EXISTS (
                SELECT 1 FROM threads_state t
                WHERE t.board_id = m.board_id AND t.thread_id = m.thread_id AND t.is_premium
           )
        """
    )

    # ── users: премиум-статус ───────────────────────────────────
    op.add_column('users', sa.Column('premium_until', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'premium_until')
    op.drop_column('media', 'is_premium')

    op.add_column('threads_state', sa.Column('is_private', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('threads_state', sa.Column('access_code_hash', sa.String(length=64), nullable=True))
    op.execute("UPDATE threads_state SET is_private = is_premium")
    op.drop_column('threads_state', 'is_premium')

    op.add_column('boards', sa.Column('is_private', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('boards', sa.Column('access_code_hash', sa.String(length=64), nullable=True))
    op.execute("UPDATE boards SET is_private = is_premium")
    op.drop_column('boards', 'is_premium')
