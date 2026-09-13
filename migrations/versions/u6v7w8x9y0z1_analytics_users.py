"""аналитика посещаемости, след сессий, статистика по аккаунту и аудит админов

Revision ID: u6v7w8x9y0z1
Revises: t5u6v7w8x9y0
Create Date: 2026-09-13 00:00:00.000000

Этап «полноценная админка»: вкладки «Статистика» и «Пользователи».

* `page_hits` — посещения сайта и события интерфейса (своя аналитика: только
  хеш IP, реферер хостом, без внешних счётчиков);
* `sessions.ip_hash / user_agent / last_seen_at` — след входа для карточки
  пользователя (кто, откуда, когда заходил);
* `view_stats.user_id / download_stats.user_id` — привязка просмотров и
  скачиваний к аккаунту (у старых записей останется NULL);
* `admin_audit` — журнал действий администратора.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'u6v7w8x9y0z1'
down_revision: Union[str, None] = 't5u6v7w8x9y0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Посещения сайта и события ───────────────────────────────
    op.create_table(
        'page_hits',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('kind', sa.String(length=16), nullable=False, server_default='page'),
        sa.Column('path', sa.String(length=255), nullable=False, server_default='/'),
        sa.Column('event', sa.String(length=64), nullable=True),
        sa.Column('session_id', sa.String(length=40), nullable=True),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('ip_hash', sa.String(length=64), nullable=True),
        sa.Column('referrer_host', sa.String(length=120), nullable=True),
        sa.Column('utm_source', sa.String(length=80), nullable=True),
        sa.Column('device', sa.String(length=16), nullable=True),
        sa.Column('browser', sa.String(length=32), nullable=True),
        sa.Column('os', sa.String(length=32), nullable=True),
        sa.Column('is_bot', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_new_visit', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index('ix_page_hits_created_at', 'page_hits', ['created_at'])
    op.create_index('ix_page_hits_session_id', 'page_hits', ['session_id'])
    op.create_index('ix_page_hits_user_id', 'page_hits', ['user_id'])
    op.create_index('ix_page_hits_kind_path', 'page_hits', ['kind', 'path'])

    # ── 2. След сессий ─────────────────────────────────────────────
    op.add_column('sessions', sa.Column('ip_hash', sa.String(length=64), nullable=True))
    op.add_column('sessions', sa.Column('user_agent', sa.String(length=255), nullable=True))
    op.add_column('sessions', sa.Column('last_seen_at', sa.DateTime(), nullable=True))
    op.create_index('ix_sessions_last_seen_at', 'sessions', ['last_seen_at'])

    # ── 3. Статистика по аккаунту ──────────────────────────────────
    op.add_column(
        'view_stats',
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index('ix_view_stats_user_id', 'view_stats', ['user_id'])
    op.add_column(
        'download_stats',
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index('ix_download_stats_user_id', 'download_stats', ['user_id'])

    # ── 4. Аудит админских действий ────────────────────────────────
    op.create_table(
        'admin_audit',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('actor', sa.String(length=255), nullable=True),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('target', sa.String(length=120), nullable=True),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('ip_hash', sa.String(length=64), nullable=True),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index('ix_admin_audit_created_at', 'admin_audit', ['created_at'])
    op.create_index('ix_admin_audit_user_id', 'admin_audit', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_admin_audit_user_id', table_name='admin_audit')
    op.drop_index('ix_admin_audit_created_at', table_name='admin_audit')
    op.drop_table('admin_audit')

    op.drop_index('ix_download_stats_user_id', table_name='download_stats')
    op.drop_column('download_stats', 'user_id')
    op.drop_index('ix_view_stats_user_id', table_name='view_stats')
    op.drop_column('view_stats', 'user_id')

    op.drop_index('ix_sessions_last_seen_at', table_name='sessions')
    op.drop_column('sessions', 'last_seen_at')
    op.drop_column('sessions', 'user_agent')
    op.drop_column('sessions', 'ip_hash')

    op.drop_index('ix_page_hits_kind_path', table_name='page_hits')
    op.drop_index('ix_page_hits_user_id', table_name='page_hits')
    op.drop_index('ix_page_hits_session_id', table_name='page_hits')
    op.drop_index('ix_page_hits_created_at', table_name='page_hits')
    op.drop_table('page_hits')
