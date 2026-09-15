"""Тарифы подписки, стартовая акция и журнал платежей (Фаза 4, шаг 1).

Модель «открытый архив»: Free видит открытые разделы (с рекламой), Premium —
приватные разделы, скачивание и без рекламы. Здесь появляется то, что нужно
для продаж:

* `plans` — четыре тарифа с ценами в рублях (неделя 100, месяц 350, год 2500,
  навсегда 6000) и сроком доступа;
* `pricing_promo` — стартовая акция «−50% первые 30 дней или до первых 50 оплат»;
* `payments` — журнал оплат: и для истории, и для подсчёта «первых 50 платящих».

Сами платежи (CryptoBot) подключаются следующим шагом — таблица уже готова.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-09-15 11:30:00.000000

"""
from datetime import datetime, timedelta
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0d1e2f3a4b5'
down_revision: Union[str, None] = 'b9c0d1e2f3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Стартовые тарифы: править можно из админки, здесь — чтобы витрина работала сразу
PLANS = [
    ("week", "Неделя", "7 дней доступа", 7, 100, 10, None),
    ("month", "Месяц", "30 дней доступа", 30, 350, 20, "выгодно"),
    ("year", "Год", "365 дней доступа", 365, 2500, 30, None),
    ("forever", "Навсегда", "Доступ без срока", 36500, 6000, 40, "навсегда"),
]


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("price_rub", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("badge", sa.String(length=32), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("code"),
    )

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

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("plan_code", sa.String(length=16), nullable=False),
        sa.Column("amount_rub", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discount_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("external_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("premium_until", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payments_user", "payments", ["user_id"])
    op.create_index("ix_payments_status", "payments", ["status"])

    # ── Данные: тарифы и стартовая акция ────────────────────────────
    plans_table = sa.table(
        "plans",
        sa.column("code", sa.String),
        sa.column("title", sa.String),
        sa.column("description", sa.String),
        sa.column("days", sa.Integer),
        sa.column("price_rub", sa.Integer),
        sa.column("sort_order", sa.Integer),
        sa.column("badge", sa.String),
    )
    op.bulk_insert(
        plans_table,
        [
            {
                "code": code,
                "title": title,
                "description": description,
                "days": days,
                "price_rub": price,
                "sort_order": order,
                "badge": badge,
            }
            for code, title, description, days, price, order, badge in PLANS
        ],
    )

    now = datetime.utcnow().replace(microsecond=0)
    promo_table = sa.table(
        "pricing_promo",
        sa.column("id", sa.Integer),
        sa.column("enabled", sa.Boolean),
        sa.column("percent", sa.Integer),
        sa.column("starts_at", sa.DateTime),
        sa.column("ends_at", sa.DateTime),
        sa.column("max_paid", sa.Integer),
        sa.column("note", sa.String),
    )
    op.bulk_insert(
        promo_table,
        [
            {
                "id": 1,
                "enabled": True,
                "percent": 50,
                "starts_at": now,
                "ends_at": now + timedelta(days=30),
                "max_paid": 50,
                "note": "Старт: −50% первые 30 дней или до первых 50 оплат",
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_user", table_name="payments")
    op.drop_table("payments")
    op.drop_table("pricing_promo")
    op.drop_table("plans")
