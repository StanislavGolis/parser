"""источник 4chan (chan4): заводим в реестре (выключенным)

Разделы 4chan читаются официальным JSON API: каталог `/catalog.json`, тред
`/thread/{no}.json`, медиа — `i.4cdn.org` (адаптер `src/parsers/chan4.py`).
Источник выключен: сначала его включает админ, первая доска — `/s/`
(Sexy Beautiful Women). Свой контейнер-прогон — `parser-chan4`
(`PARSER_SOURCE=chan4`).

Треды 4chan живут недолго (собственный архив — несколько суток), поэтому у
источника частое расписание (`schedule_minutes=10`) и вежливая частота запросов
(`rate_limit_rps=1.0` — требование API 4chan). История, которая уже ушла с
борды, добирается из сторонних архивов инструментом `src/tools/chan4_import.py`
(desuarchive / archiveofsins / fireden), а не вторым источником: раздел `/s/`
должен остаться одним, без дублей вида `/s-archive/`.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-09-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, None] = 'c6d7e8f9a0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO sources
            (code, title, kind, base_url, is_enabled, schedule_minutes,
             rate_limit_rps, budget_minutes, sort_order, config)
        VALUES
            ('chan4', '4chan', 'json', 'https://a.4cdn.org', false, 10,
             1.0, 60, 20,
             '{"boards": ["s"], "note": "официальный API 4chan; первая доска — /s/"}'::jsonb)
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    # Удаляем источник вместе с его досками/тредами/файлами (каскад по FK)
    op.execute("DELETE FROM sources WHERE code = 'chan4'")
