"""sources + parse_runs: подготовка к мульти-источникам (2ch, slivach, …)

Вводим реестр источников: доски и файлы привязываются к источнику, у каждого
источника свои настройки (базовый URL, конфиг адаптера, расписание, лимиты) и
своя история прогонов. Все существующие данные становятся источником `dvach`,
поэтому миграция аддитивная: старый код продолжает работать.

Revision ID: v7w8x9y0z1a2
Revises: u6v7w8x9y0z1
Create Date: 2026-09-13 02:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'v7w8x9y0z1a2'
down_revision: Union[str, None] = 'u6v7w8x9y0z1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Реестр источников ────────────────────────────────────────
    op.create_table(
        'sources',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(32), nullable=False),
        sa.Column('title', sa.String(100), nullable=False, server_default=sa.text("''")),
        sa.Column('kind', sa.String(32), nullable=False, server_default=sa.text("'json'")),
        sa.Column('base_url', sa.String(255), nullable=False, server_default=sa.text("''")),
        sa.Column('config', JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('schedule_minutes', sa.Integer(), nullable=False, server_default=sa.text('30')),
        sa.Column('rate_limit_rps', sa.Float(), nullable=False, server_default=sa.text('1.0')),
        sa.Column('budget_minutes', sa.Integer(), nullable=False, server_default=sa.text('30')),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_sources_code'),
    )

    # 2ch — источник по умолчанию: в него переезжает вся текущая база
    op.execute(
        """
        INSERT INTO sources
            (code, title, kind, base_url, is_enabled,
             schedule_minutes, rate_limit_rps, budget_minutes, sort_order)
        VALUES ('dvach', '2ch.hk', 'json', 'https://2ch.hk', true, 30, 0.5, 30, 0)
        """
    )

    # ── 2. Доски → источник ─────────────────────────────────────────
    op.add_column('boards', sa.Column('source_id', sa.Integer(), nullable=True))
    op.execute("UPDATE boards SET source_id = (SELECT id FROM sources WHERE code = 'dvach')")
    op.alter_column('boards', 'source_id', nullable=False)
    op.create_foreign_key(
        'fk_boards_source', 'boards', 'sources', ['source_id'], ['id'], ondelete='CASCADE'
    )
    op.create_index('ix_boards_source', 'boards', ['source_id'])

    # ── 3. Треды: внешний идентификатор источника ───────────────────
    # У 2ch это номер треда, у сайтов — слаг записи («alena-omovich-sliv»).
    op.add_column('threads_state', sa.Column('external_id', sa.String(64), nullable=True))
    op.execute("UPDATE threads_state SET external_id = thread_id::text WHERE external_id IS NULL")
    op.alter_column('threads_state', 'external_id', nullable=False)
    op.create_unique_constraint(
        'uq_threads_state_board_external', 'threads_state', ['board_id', 'external_id']
    )

    # ── 4. Файлы: денормализация источника ──────────────────────────
    op.add_column('media', sa.Column('source_id', sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE media SET source_id = boards.source_id
        FROM boards WHERE media.board_id = boards.id AND media.source_id IS NULL
        """
    )
    op.create_foreign_key(
        'fk_media_source', 'media', 'sources', ['source_id'], ['id'], ondelete='SET NULL'
    )
    op.create_index('ix_media_source', 'media', ['source_id'])

    # ── 5. История прогонов ─────────────────────────────────────────
    op.create_table(
        'parse_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default=sa.text("'running'")),
        sa.Column('phase', sa.String(32), nullable=True),
        sa.Column('stats', JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(
            ['source_id'], ['sources.id'],
            name='fk_parse_runs_source', ondelete='CASCADE',
        ),
    )
    op.create_index('ix_parse_runs_source_started', 'parse_runs', ['source_id', 'started_at'])


def downgrade() -> None:
    op.drop_index('ix_parse_runs_source_started', table_name='parse_runs')
    op.drop_table('parse_runs')

    op.drop_index('ix_media_source', table_name='media')
    op.drop_constraint('fk_media_source', 'media', type_='foreignkey')
    op.drop_column('media', 'source_id')

    op.drop_constraint('uq_threads_state_board_external', 'threads_state', type_='unique')
    op.drop_column('threads_state', 'external_id')

    op.drop_index('ix_boards_source', table_name='boards')
    op.drop_constraint('fk_boards_source', 'boards', type_='foreignkey')
    op.drop_column('boards', 'source_id')

    op.drop_table('sources')
