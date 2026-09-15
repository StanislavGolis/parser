"""Гибкие акции и цены в звёздах (Фаза 4, шаг 2).

Что меняется:

* **Акции — список, а не одна строка.** Таблица `pricing_promo` (одна запись «стартовая
  акция») заменяется на `promos`: у каждой акции свои название, описание, процент,
  срок, лимит оплат и список тарифов, к которым она применяется. Включать нужную акцию
  можно под событие (запуск, праздник, «первым 50»), и они не мешают друг другу.
* **Плата звёздами Telegram.** У тарифа появляется `price_stars` — цена вручную
  (вариант A): задаётся в админке, оплата идёт через Bot API (`currency: XTR`),
  провайдер не нужен.

Скидка применяется и к рублям, и ко звёздам: процент берётся из акции, поэтому
достаточно поменять условия в админке — и витрина, и бот покажут одно и то же.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-09-15 13:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c0d1e2f3a4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Цены в звёздах Telegram (вариант A: задаются вручную) ───────
    op.add_column("plans", sa.Column("price_stars", sa.Integer(), nullable=True))

    # ── Акции: список вместо одной строки ───────────────────────────
    op.create_table(
        "promos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("percent", sa.Integer(), nullable=False, server_default="50"),
        # Включена вручную: акцию заводят заранее и включают к событию
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("starts_at", sa.DateTime(), nullable=True),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("max_paid", sa.Integer(), nullable=True),
        # На какие тарифы действует: ["week", ...]; NULL — на все
        sa.Column("applies_to", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_promos_active", "promos", ["is_active", "ends_at"])

    # ── Переносим текущую стартовую акцию, если она была настроена ──
    op.execute(
        """
        INSERT INTO promos
            (created_at, updated_at, title, description, percent, is_active,
             starts_at, ends_at, max_paid, applies_to)
        SELECT
            now(), now(),
            'Стартовая акция',
            coalesce(note, 'Скидка на все тарифы'),
            percent, enabled, starts_at, ends_at, max_paid, NULL
        FROM pricing_promo
        WHERE id = 1
        """
    )

    op.drop_table("pricing_promo")


def downgrade() -> None:
    op.create_table(
        "pricing_promo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("percent", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("max_paid", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.drop_index("ix_promos_active", table_name="promos")
    op.drop_table("promos")
    op.drop_column("plans", "price_stars")
