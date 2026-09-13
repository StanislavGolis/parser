"""media.source_order: порядок файла внутри «треда» у источника

Тред смотрят с начала: список файлов сортируется по порядку в источнике
(`post_num` из конвейера), а не по времени скачивания. Иначе новые файлы
«дописывались» в начало треда, а зритель, продолжая с места, видел сдвиг.

Существующие строки заполняем порядком появления в архиве (row_number по
`created_at, id` внутри доски и треда) — для тредов, скачанных подряд, это и
есть порядок постов; новые файлы получают точный `post_num` из парсера.

Revision ID: a2b3c4d5e6f7
Revises: z1a2b3c4d5e6
Create Date: 2026-09-13 08:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'z1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BACKFILL = """
UPDATE media AS m
SET source_order = ranked.rn
FROM (
    SELECT id, row_number() OVER (
        PARTITION BY board_id, thread_id ORDER BY created_at, id
    ) AS rn
    FROM media
) AS ranked
WHERE m.id = ranked.id AND m.source_order IS NULL
"""


def upgrade() -> None:
    op.add_column('media', sa.Column('source_order', sa.Integer(), nullable=True))
    op.create_index('ix_media_thread_order', 'media', ['thread_id', 'source_order'])
    op.execute(sa.text(BACKFILL))


def downgrade() -> None:
    op.drop_index('ix_media_thread_order', table_name='media')
    op.drop_column('media', 'source_order')
