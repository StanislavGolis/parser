"""Платежи: `external_id` под длинные идентификаторы Telegram Stars.

Инцидент 15.09.2026: первый тестовый платёж звёздами не зачислился — INSERT падал с
`value too long for type character varying(64)`. У оплат в звёздах
`telegram_payment_charge_id` длиннее 64 символов, поэтому расширяем поле до 255
(столько же у `provider_payment_charge_id`, который придёт вместе со звёздами).

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-09-15 15:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "payments",
        "external_id",
        existing_type=sa.String(length=64),
        type_=sa.String(length=255),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "payments",
        "external_id",
        existing_type=sa.String(length=255),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
