"""board management: parse_enabled, is_private, access_code_hash

Revision ID: e7f3a1c9b2d4
Revises: 06bd3e2d4425
Create Date: 2026-09-06 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f3a1c9b2d4'
down_revision: Union[str, None] = '06bd3e2d4425'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('boards', sa.Column('parse_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('boards', sa.Column('is_private', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('boards', sa.Column('access_code_hash', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('boards', 'access_code_hash')
    op.drop_column('boards', 'is_private')
    op.drop_column('boards', 'parse_enabled')