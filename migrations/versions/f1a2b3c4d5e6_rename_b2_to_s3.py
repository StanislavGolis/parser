"""rename media.b2_bucket/b2_key -> s3_bucket/s3_key

Revision ID: f1a2b3c4d5e6
Revises: c9d0e1f2a3b4
Create Date: 2026-09-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('media', 'b2_bucket', new_column_name='s3_bucket')
    op.alter_column('media', 'b2_key', new_column_name='s3_key')
    # Имя индекса приводим к модели (ix_media_s3_key)
    op.execute('ALTER INDEX IF EXISTS ix_media_b2_key RENAME TO ix_media_s3_key')


def downgrade() -> None:
    op.execute('ALTER INDEX IF EXISTS ix_media_s3_key RENAME TO ix_media_b2_key')
    op.alter_column('media', 's3_key', new_column_name='b2_key')
    op.alter_column('media', 's3_bucket', new_column_name='b2_bucket')
