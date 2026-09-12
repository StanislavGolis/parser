"""вход в админку по email+паролю и восстановление пароля

Revision ID: t5u6v7w8x9y0
Revises: s4t5u6v7w8x9
Create Date: 2026-09-12 15:30:00.000000

Раньше админка открывалась одним общим токеном (`ADMIN_TOKEN` из .env): если он
потерян — доступ можно вернуть только с сервера. Добавляем админ-аккаунты:

* `users.is_admin` — кому разрешён вход в админку и восстановление пароля
  (список `ADMIN_EMAILS`, аккаунты заводятся автоматически);
* `admin_password_resets` — одноразовые токены восстановления: в БД хранится
  только sha256(токена), живёт `ADMIN_RESET_TTL_MINUTES`, помечается использованным.

Токен `ADMIN_TOKEN` остаётся рабочим для скриптов и как резервный вход.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 't5u6v7w8x9y0'
down_revision: Union[str, None] = 's4t5u6v7w8x9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        'admin_password_resets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
    )
    op.create_index(
        'ix_admin_password_resets_user_id', 'admin_password_resets', ['user_id']
    )
    op.create_unique_constraint(
        'uq_admin_password_resets_token_hash', 'admin_password_resets', ['token_hash']
    )


def downgrade() -> None:
    op.drop_constraint(
        'uq_admin_password_resets_token_hash', 'admin_password_resets', type_='unique'
    )
    op.drop_index('ix_admin_password_resets_user_id', table_name='admin_password_resets')
    op.drop_table('admin_password_resets')
    op.drop_column('users', 'is_admin')
