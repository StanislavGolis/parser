"""Журнал постов в Telegram-канал (менеджер канала, шаг 1).

Публикация ручная: админ собирает тизер в админке (мозаика 2×2 из превью), правит
подпись и нажимает «Опубликовать». Каждая отправка фиксируется здесь: статус,
id сообщения в канале, текст ошибки — чтобы видеть историю и повторять неудачные.

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-09-15 09:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_posts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="teaser"),
        sa.Column("caption", sa.Text(), nullable=False, server_default=""),
        sa.Column("media_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("image_mode", sa.String(length=12), nullable=False, server_default="mosaic"),
        sa.Column("button_text", sa.String(length=64), nullable=True),
        sa.Column("button_url", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("channel", sa.String(length=120), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_telegram_posts_created", "telegram_posts", ["created_at"])
    op.create_index(
        "ix_telegram_posts_status_scheduled", "telegram_posts", ["status", "scheduled_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_posts_status_scheduled", table_name="telegram_posts")
    op.drop_index("ix_telegram_posts_created", table_name="telegram_posts")
    op.drop_table("telegram_posts")
