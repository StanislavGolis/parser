"""источник slivach: заводим в реестре (выключенным)

Второй сайт-источник появляется в реестре заранее, чтобы у него был свой
контейнер-прогон (`parser-slivach`, `PARSER_SOURCE=slivach`). Источник
выключен: парсинг включит админ, когда адаптер будет готов (этап 5).

Revision ID: w8x9y0z1a2b3
Revises: v7w8x9y0z1a2
Create Date: 2026-09-13 03:05:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'w8x9y0z1a2b3'
down_revision: Union[str, None] = 'v7w8x9y0z1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `boards` в конфиге пока пуст: категории-разделы появятся, когда адаптер
    # будет описан (или их заведёт сам парсер при первом прогоне).
    op.execute(
        """
        INSERT INTO sources
            (code, title, kind, base_url, is_enabled, schedule_minutes,
             rate_limit_rps, budget_minutes, sort_order, config)
        VALUES
            ('slivach', 'slivach.com', 'html', 'https://slivach.com', false, 1440,
             1.0, 60, 10,
             '{"boards": [], "note": "адаптер в разработке"}'::jsonb)
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    # Удаляем источник вместе с его досками/тредами/файлами (каскад по FK)
    op.execute("DELETE FROM sources WHERE code = 'slivach'")
