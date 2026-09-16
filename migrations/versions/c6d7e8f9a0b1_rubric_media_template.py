"""Единый шаблон настроек рубрик: мозаика и приложения

Раньше у каждой рубрики был свой набор ключей в `options` (`board_photos`, `photos`,
размытие только для мозаики). Теперь шаблон общий:

* мозаика — `tiles` (0…4 плиток, 0 = без мозаики), `blur` (размытие 0…24);
* приложения — `photos` (сколько кадров приложить), `photos_per_board` (по сколько
  кадров брать из каждого раздела), `photos_blur` (размытие приложений, 0 = как есть),
  `quality` (`web` | `thumb`).

Миграция приводит сохранённые настройки к этому виду: `board_photos` у «Свежего»
становится `photos`, а рубрикам дописываются новые ключи (существующие значения не
трогаем — у «Раздела дня» мозаики нет, `tiles` = 0).

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
"""

import sqlalchemy as sa
from alembic import op

revision: str = "c6d7e8f9a0b1"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None

# Новые ключи: значения по умолчанию для каждой рубрики
PATCHES = (
    (
        "fresh",
        """
        UPDATE telegram_rubrics
        SET options = (coalesce(options, '{}'::jsonb) - 'board_photos')
            || jsonb_build_object(
                 'photos', coalesce((coalesce(options, '{}'::jsonb) ->> 'board_photos')::int, 4),
                 'photos_per_board', 1,
                 'photos_blur', 0
               )
        WHERE code = 'fresh'
        """,
    ),
    (
        "board_day",
        """
        UPDATE telegram_rubrics
        SET options = coalesce(options, '{}'::jsonb)
            || jsonb_build_object('tiles', 0, 'photos_per_board', 1, 'photos_blur', 0)
        WHERE code = 'board_day'
        """,
    ),
    (
        "top_week",
        """
        UPDATE telegram_rubrics
        SET options = coalesce(options, '{}'::jsonb)
            || jsonb_build_object('photos', 0, 'photos_per_board', 1, 'photos_blur', 0)
        WHERE code = 'top_week'
        """,
    ),
)


def upgrade() -> None:
    for _code, statement in PATCHES:
        op.execute(sa.text(statement))


def downgrade() -> None:
    # Возвращаем прежнее имя ключа у «Свежего» и убираем новые
    op.execute(
        sa.text(
            """
            UPDATE telegram_rubrics
            SET options = (coalesce(options, '{}'::jsonb)
                || jsonb_build_object('board_photos', coalesce((options ->> 'photos')::int, 4)))
                - 'photos' - 'photos_per_board' - 'photos_blur'
            WHERE code = 'fresh'
            """
        )
    )
    for code in ("board_day", "top_week"):
        op.execute(
            sa.text(
                "UPDATE telegram_rubrics SET options = coalesce(options, '{}'::jsonb)"
                " - 'photos_per_board' - 'photos_blur'"
                " WHERE code = :code"
            ).bindparams(code=code)
        )
