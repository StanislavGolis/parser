"""слаги разделов slivach: убрать префикс источника

Разделы источника slivach заводились как `slivach-<категория>` (`slivach-asmr`),
хотя на сайте это просто категории. Префикс убираем — адрес раздела стал короче
и совпал с источником (`/asmr`).

Конфликты исключены проверкой: слаг меняется только если он свободен
(`boards.slug` UNIQUE), иначе доска остаётся со старым слагом — данные не теряются.
Старые адреса `/board/slivach-<категория>` отдают 308 на новый (см. `web/`).

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-09-13 12:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Категории сайта-источника: нужны для отката (вернуть префикс этим разделам).
CATEGORIES = [
    "modeli",
    "asmr",
    "aktrisy",
    "pevitsy",
    "sportsmenki",
    "blogershi",
    "strimershi",
    "kospley",
    "tiktokershi",
    "znamenitosti",
]

STRIP_PREFIX = """
UPDATE boards
SET slug = substring(slug from 9)
WHERE slug LIKE 'slivach-%'
  AND NOT EXISTS (
      SELECT 1 FROM boards AS taken WHERE taken.slug = substring(boards.slug from 9)
  )
"""

RESTORE_PREFIX = """
UPDATE boards
SET slug = 'slivach-' || slug
WHERE slug = ANY(:categories)
  AND NOT EXISTS (
      SELECT 1 FROM boards AS taken WHERE taken.slug = 'slivach-' || boards.slug
  )
"""


def upgrade() -> None:
    op.execute(sa.text(STRIP_PREFIX))


def downgrade() -> None:
    op.execute(sa.text(RESTORE_PREFIX).bindparams(sa.bindparam("categories", value=CATEGORIES)))
