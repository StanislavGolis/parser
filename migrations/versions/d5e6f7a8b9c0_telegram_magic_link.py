"""Telegram-аккаунты и одноразовые ссылки входа (модель Dredger 2.0).

Модель: Telegram продаёт и даёт доступ, сайт показывает. Аккаунт сайта = Telegram ID
(пароль не нужен), вход — по одноразовой ссылке: бот присылает `/auth/magic?token=…`,
ссылка живёт `MAGIC_LINK_TTL_MINUTES` и после использования гаснет.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Аккаунт может существовать без email: его заводит бот по Telegram ID
    op.alter_column("users", "email", existing_type=sa.String(255), nullable=True)
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=True)
    op.add_column("users", sa.Column("telegram_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("telegram_username", sa.String(64), nullable=True))
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)

    op.create_table(
        "auth_magic_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_ip", sa.String(64), nullable=True),
    )
    op.create_index("ix_auth_magic_links_token_hash", "auth_magic_links", ["token_hash"], unique=True)
    op.create_index("ix_auth_magic_links_user_id", "auth_magic_links", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_auth_magic_links_user_id", table_name="auth_magic_links")
    op.drop_index("ix_auth_magic_links_token_hash", table_name="auth_magic_links")
    op.drop_table("auth_magic_links")
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_column("users", "telegram_username")
    op.drop_column("users", "telegram_id")
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=False)
    op.alter_column("users", "email", existing_type=sa.String(255), nullable=False)
