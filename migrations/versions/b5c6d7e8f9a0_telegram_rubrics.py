"""Рубрики автопостинга канала: telegram_rubrics + rubric в telegram_posts

Раньше автопост всегда собирал одну и ту же «подборку за сутки». Теперь постов
несколько типов, и каждый включается/настраивается в админке:

* `fresh` — «Свежее»: мозаика 2×2 из свежих файлов + список разделов с приростом
  за сутки и по фото из каждого раздела;
* `board_day` — «Раздел дня»: несколько фото из одного треда + описание раздела;
* `top_week` — «Топ недели»: мозаика 2×2 + разделы, которые смотрели и сохраняли
  за неделю.

Рубрика знает свой минимальный интервал (`min_gap_hours`) — «Топ недели» не может
выходить чаще раза в неделю, «Свежее» может раз в сутки. Планировщик выбирает ту
рубрику, которая «просрочена» сильнее всего.

В `telegram_posts` добавляются `rubric` (какая рубрика собрала пост) и
`rubric_meta` (какие файлы пошли на мозаику и в альбом, качество, размытие) —
по ним пост восстанавливается при публикации из карантина.

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
"""
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b5c6d7e8f9a0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


# Стартовые настройки рубрик. Рубрики создаются выключенными: включить их можно
# в админке, когда тексты и картинки проверены в предпросмотре.
RUBRIC_SEED = (
    {
        "code": "fresh",
        "title": "Свежее",
        "sort_order": 10,
        "min_gap_hours": 12,
        "options": {
            "hours": 24,
            "boards_count": 4,
            "tiles": 4,
            "board_photos": 4,
            "blur": 15,
            "quality": "web",
        },
    },
    {
        "code": "board_day",
        "title": "Раздел дня",
        "sort_order": 20,
        "min_gap_hours": 24,
        "options": {
            "board": "",
            "photos": 5,
            "blur": 0,
            "quality": "web",
        },
    },
    {
        "code": "top_week",
        "title": "Топ недели",
        "sort_order": 30,
        "min_gap_hours": 168,
        "options": {
            "days": 7,
            "boards_count": 3,
            "tiles": 4,
            "blur": 15,
            "sort": "activity",
        },
    },
)


def upgrade() -> None:
    op.create_table(
        "telegram_rubrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        # Как часто рубрику можно собирать (часы): 12 — «Свежее», 168 — «Топ недели»
        sa.Column("min_gap_hours", sa.Integer(), nullable=False, server_default="24"),
        # Параметры рубрики (число плиток, разделов, фото, размытие, раздел дня и т.п.)
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_telegram_rubrics_code"),
    )

    op.add_column("telegram_posts", sa.Column("rubric", sa.String(length=24), nullable=True))
    op.add_column(
        "telegram_posts",
        sa.Column("rubric_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_telegram_posts_rubric", "telegram_posts", ["rubric", "created_at"])

    rubrics = sa.table(
        "telegram_rubrics",
        sa.column("code", sa.String),
        sa.column("title", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        sa.column("min_gap_hours", sa.Integer),
        sa.column("options", postgresql.JSONB),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    now = datetime.utcnow()
    op.bulk_insert(
        rubrics,
        [
            {
                **item,
                "enabled": False,
                "created_at": now,
                "updated_at": now,
            }
            for item in RUBRIC_SEED
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_posts_rubric", table_name="telegram_posts")
    op.drop_column("telegram_posts", "rubric_meta")
    op.drop_column("telegram_posts", "rubric")
    op.drop_table("telegram_rubrics")
