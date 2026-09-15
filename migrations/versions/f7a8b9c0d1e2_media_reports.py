"""Жалобы на файлы и блок-лист хешей (модерация, фаза 5).

Жалоба с сайта попадает в очередь админки (`/admin/reports`); разбор — скрытие
файла, скрытие треда, удаление файла с объектом в S3 или отклонение. При причине
`csam` доступ закрывается автоматически (файл + тред) и хеш уходит в блок-лист,
чтобы файл не вернулся ни через пересканирование, ни через архивный импорт.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-14 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "media_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=24), nullable=False, server_default="other"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_reports_created_at", "media_reports", ["created_at"])
    op.create_index("ix_media_reports_user_id", "media_reports", ["user_id"])
    op.create_index("ix_media_reports_media", "media_reports", ["media_id"])
    op.create_index("ix_media_reports_status_created", "media_reports", ["status", "created_at"])

    op.create_table(
        "blocked_hashes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256", name="uq_blocked_hashes_sha256"),
    )


def downgrade() -> None:
    op.drop_table("blocked_hashes")
    op.drop_index("ix_media_reports_status_created", table_name="media_reports")
    op.drop_index("ix_media_reports_media", table_name="media_reports")
    op.drop_index("ix_media_reports_user_id", table_name="media_reports")
    op.drop_index("ix_media_reports_created_at", table_name="media_reports")
    op.drop_table("media_reports")
