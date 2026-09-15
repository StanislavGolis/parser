"""Автопостинг, расписание и розыгрыши в Telegram-канале (шаги 2–4).

Три темы одного направления:

* `telegram_autopost` — настройки автопостинга (лимит в сутки, окна тишины,
  белый список разделов, режим карантина). Строка одна, id=1.
* `giveaways` + `giveaway_entries` — розыгрыши премиум-подписки: участие через бота
  с проверкой подписки на канал, победителю продлеваем `premium_until`.

Отложенные посты живут в уже существующей `telegram_posts` (статус `scheduled` +
`scheduled_at`), отдельная таблица им не нужна.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-09-15 10:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b9c0d1e2f3a4'
down_revision: Union[str, None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_autopost",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("posts_per_day", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("quiet_from", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("quiet_to", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("require_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("boards", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("period", sa.String(length=8), nullable=False, server_default="day"),
        sa.Column("blur", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("last_check_at", sa.DateTime(), nullable=True),
        sa.Column("last_post_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "giveaways",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=12), nullable=False, server_default="daily"),
        sa.Column("prize_days", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("winners", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("announce_message_id", sa.BigInteger(), nullable=True),
        sa.Column("result_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_giveaways_status_ends", "giveaways", ["status", "ends_at"])

    op.create_table(
        "giveaway_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("giveaway_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["giveaway_id"], ["giveaways.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("giveaway_id", "user_id", name="uq_giveaway_entries_user"),
    )
    op.create_index("ix_giveaway_entries_giveaway", "giveaway_entries", ["giveaway_id"])


def downgrade() -> None:
    op.drop_index("ix_giveaway_entries_giveaway", table_name="giveaway_entries")
    op.drop_table("giveaway_entries")
    op.drop_index("ix_giveaways_status_ends", table_name="giveaways")
    op.drop_table("giveaways")
    op.drop_table("telegram_autopost")
