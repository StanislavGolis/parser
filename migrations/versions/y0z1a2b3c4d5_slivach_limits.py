"""slivach: стартовые лимиты и конфиг адаптера (видео включено)

Категории сайта и записи выбираются в админке («Разделы сайта» → «Загрузить
записи»), поэтому списка `boards` в конфиге нет: разделы заводит администратор,
и новые «треды» (записи) по умолчанию выключены (`parse_mode=selected`).

Лимиты каталога сняты (`max_pages=0`, `max_records=0`): в списке сразу видно все
записи категории, а скачиваются только выбранные. Видео включено — сайт-источник
без него неполный; объём регулируется бюджетом прогона и включением записей.

Revision ID: y0z1a2b3c4d5
Revises: x9y0z1a2b3c4
Create Date: 2026-09-13 05:20:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'y0z1a2b3c4d5'
down_revision: Union[str, None] = 'x9y0z1a2b3c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONFIG = {
    "note": (
        "адаптер готов (этап 5): категории выбираются во вкладке «Разделы сайта», "
        "записи — кнопкой «Загрузить записи», они включаются поштучно"
    ),
    "boards": [],
    "max_pages": 0,        # 0 — обходить всю пагинацию категории
    "max_records": 0,      # 0 — показывать все записи (качаются выбранные)
    "include_images": True,
    "include_video": True,
}

PREVIOUS_CONFIG = {"note": "адаптер в разработке", "boards": []}


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE sources SET config = CAST(:cfg AS jsonb), schedule_minutes = 60, "
            "rate_limit_rps = 1.0, budget_minutes = 60 WHERE code = 'slivach'"
        ).bindparams(cfg=json.dumps(CONFIG, ensure_ascii=False))
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE sources SET config = CAST(:cfg AS jsonb), schedule_minutes = 1440, "
            "rate_limit_rps = 1.0, budget_minutes = 60 WHERE code = 'slivach'"
        ).bindparams(cfg=json.dumps(PREVIOUS_CONFIG, ensure_ascii=False))
    )
