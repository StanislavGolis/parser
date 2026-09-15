"""Тарифная сетка в звёздах: 3 дня / месяц / год / навсегда.

Витрина продаёт только за звёзды Telegram, поэтому состав и подписи тарифов
приводим к решению владельца:

* `week` (7 дней) → `days3` (3 дня) — дешёвая точка входа;
* у всех тарифов заполняется `price_stars` (если было пусто);
* рублёвая цена остаётся в базе как справочная (для журнала и учёта), но в
  витрине и боте покупатель видит только звёзды;
* в акциях (`promos.applies_to`) код `week` заменяется на `days3`, иначе акция
  «на неделю» потеряла бы свой тариф.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-15 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# code, title, description, days, price_stars, sort_order, badge
PLANS = [
    ("days3", "3 дня", "3 дня доступа", 3, 50, 5, None),
    ("month", "Месяц", "30 дней доступа", 30, 250, 20, "выгодно"),
    ("year", "Год", "365 дней доступа", 365, 1700, 30, None),
    ("forever", "Навсегда", "Доступ без срока", 36500, 4000, 40, "навсегда"),
]


def upgrade() -> None:
    # ── Код `week` → `days3` (и в акциях, которые на него ссылались) ──
    op.execute(
        """
        UPDATE promos
        SET applies_to = (
            SELECT jsonb_agg(CASE WHEN value = 'week' THEN 'days3' ELSE value END)
            FROM jsonb_array_elements_text(applies_to) AS value
        )
        WHERE applies_to @> '["week"]'::jsonb
        """
    )
    op.execute("UPDATE plans SET code = 'days3' WHERE code = 'week'")

    # ── Состав, подписи и цены в звёздах ────────────────────────────
    for code, title, description, days, stars, order, badge in PLANS:
        op.execute(
            sa.text(
                """
                INSERT INTO plans (code, title, description, days, price_rub, price_stars,
                                   is_active, sort_order, badge, updated_at)
                VALUES (:code, :title, :description, :days, 0, :stars, true, :order,
                        :badge, now())
                ON CONFLICT (code) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    days = EXCLUDED.days,
                    price_stars = EXCLUDED.price_stars,
                    sort_order = EXCLUDED.sort_order,
                    badge = EXCLUDED.badge,
                    is_active = true,
                    updated_at = now()
                """
            ).bindparams(
                code=code,
                title=title,
                description=description,
                days=days,
                stars=stars,
                order=order,
                badge=badge,
            )
        )

    # ── Справочные рубли: у 3 дней — как было у недели ──────────────
    op.execute("UPDATE plans SET price_rub = 100 WHERE code = 'days3' AND price_rub = 0")


def downgrade() -> None:
    op.execute("UPDATE plans SET code = 'week' WHERE code = 'days3'")
    op.execute(
        """
        UPDATE promos
        SET applies_to = (
            SELECT jsonb_agg(CASE WHEN value = 'days3' THEN 'week' ELSE value END)
            FROM jsonb_array_elements_text(applies_to) AS value
        )
        WHERE applies_to @> '["days3"]'::jsonb
        """
    )
