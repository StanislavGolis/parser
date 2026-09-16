"""Цены в USDT для оплаты криптой (Crypto Pay / CryptoBot).

Счёт в Crypto Pay выставляется в конкретной сумме USDT, поэтому цена хранится в
центах (`price_usdt_cents`, 150 = 1.50 USDT) — без округлений и без зависимости от
курса в момент оплаты. Суммы задаются в админке (вкладка «Тарифы»).

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-09-16 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4b5c6d7e8f9'
down_revision: Union[str, None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Стартовые суммы: примерно соответствуют цене в звёздах (1 ⭐ ≈ 0.013–0.02 $).
PRICES = {
    "days3": 100,        # 1.00 USDT
    "month": 500,        # 5.00 USDT
    "year": 3400,        # 34.00 USDT
    "forever": 8000,     # 80.00 USDT
}


def upgrade() -> None:
    op.add_column("plans", sa.Column("price_usdt_cents", sa.Integer(), nullable=True))
    for code, cents in PRICES.items():
        op.execute(
            sa.text(
                "UPDATE plans SET price_usdt_cents = :cents WHERE code = :code"
            ).bindparams(cents=cents, code=code)
        )


def downgrade() -> None:
    op.drop_column("plans", "price_usdt_cents")
