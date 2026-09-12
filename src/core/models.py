# src/core/models.py
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, DateTime, BigInteger, Boolean, Text,
    ForeignKey, Enum, Float, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Board(Base):
    """Доска / раздел форума."""
    __tablename__ = "boards"

    id = Column(Integer, primary_key=True)
    slug = Column(String(50), unique=True, nullable=False)
    title = Column(String(100), nullable=False, default="")
    description = Column(Text, nullable=True)
    is_visible = Column(Boolean, nullable=False, default=False)
    # Управление из админки (этап: админ-панель). По умолчанию всё выключено:
    # доска не парсится и не показывается, пока админ не включит явно.
    parse_enabled = Column(Boolean, nullable=False, default=False)  # доска участвует в парсинге
    is_private = Column(Boolean, nullable=False, default=False)     # контент по коду доступа
    access_code_hash = Column(String(64), nullable=True)            # sha256 кода доступа
    sort_order = Column(Integer, nullable=False, default=0)         # порядок парсинга (очередь)
    parse_mode = Column(String(16), nullable=False, default="selected")  # all | selected — как выбирать треды

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    threads_state = relationship(
        "ThreadState",
        back_populates="board",
        passive_deletes=True,  # каскад выполняет БД (ON DELETE CASCADE)
    )
    media = relationship(
        "Media",
        back_populates="board",
        passive_deletes=True,
    )


class ThreadState(Base):
    """Служебная таблица для инкрементального парсинга тредов."""
    __tablename__ = "threads_state"
    __table_args__ = (
        UniqueConstraint("board_id", "thread_id", name="uq_threads_state_board_thread"),
    )

    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id", ondelete="CASCADE"), nullable=False)
    thread_id = Column(Integer, nullable=False)  # внешний ID треда на форуме

    # Метаданные треда (для отображения списка тредов на сайте/в админке)
    subject = Column(String(500), nullable=True)          # тема треда (catalog.subject)
    comment = Column(Text, nullable=True)                 # текст ОП без HTML (обрезанный)
    thread_timestamp = Column(DateTime, nullable=True)    # время создания треда (catalog.timestamp)

    posts_count = Column(Integer, nullable=False, default=0)
    files_count = Column(Integer, nullable=False, default=0)
    files_detected = Column(Integer, nullable=False, default=0)  # файлов в треде (res/{id}.json, до загрузки)
    views_count = Column(Integer, nullable=False, default=0)  # просмотры треда (catalog.views)
    last_scanned_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    # Управление из админки (этап: управление контентом)
    parse_enabled = Column(Boolean, nullable=False, default=False)  # тред участвует в скачивании
    is_visible = Column(Boolean, nullable=False, default=False)     # показывать публично
    is_private = Column(Boolean, nullable=False, default=False)     # контент только по коду
    access_code_hash = Column(String(64), nullable=True)            # sha256 кода доступа треда

    board = relationship("Board", back_populates="threads_state")


class Media(Base):
    """Медиафайл, скачанный с форума."""
    __tablename__ = "media"
    __table_args__ = (
        Index("ix_media_board_created", "board_id", "created_at"),
        Index("ix_media_popularity", "popularity_score"),
    )

    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id", ondelete="CASCADE"), nullable=False)
    thread_id = Column(Integer, nullable=False)  # внешний ID треда (источник)

    original_name = Column(String(255), nullable=False)  # displayname с форума
    source_url = Column(String(500), nullable=True)
    file_hash = Column(String(64), unique=True, nullable=True)  # SHA-256 после скачивания
    source_md5 = Column(String(32), nullable=False, index=True)  # md5 из API двача
    file_size = Column(BigInteger, nullable=False, default=0)
    mime_type = Column(String(100), nullable=False, default="application/octet-stream")
    media_type = Column(
        Enum("image", "video", name="media_type_enum"),
        nullable=False,
    )

    s3_bucket = Column(String(255), nullable=True)
    s3_key = Column(String(500), nullable=True, index=True)
    local_path = Column(String(500), nullable=True)  # относительный путь в локальном кэше
    # Деривативы для оптимизации трафика: {"thumb": key, "web": key}
    variants = Column(JSONB, nullable=True)
    duration_seconds = Column(Float, nullable=True)  # длительность видео (для бейджа)

    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)

    download_status = Column(
        Enum("new", "downloaded", "uploaded", "verified", "missing", name="download_status_enum"),
        nullable=False,
        default="new",
    )
    is_visible = Column(Boolean, nullable=False, default=True)
    is_active = Column(Boolean, nullable=False, default=True)
    duplicate_of_id = Column(Integer, ForeignKey("media.id", ondelete="SET NULL"), nullable=True)

    views_count = Column(Integer, nullable=False, default=0)
    downloads_count = Column(Integer, nullable=False, default=0)
    popularity_score = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    board = relationship("Board", back_populates="media")


class ViewStat(Base):
    """Статистика просмотров по IP-хешу (анти-накрутка)."""
    __tablename__ = "view_stats"
    __table_args__ = (
        Index("ix_view_stats_media_viewed", "media_id", "viewed_at"),
    )

    id = Column(Integer, primary_key=True)
    media_id = Column(Integer, ForeignKey("media.id", ondelete="CASCADE"), nullable=False)
    ip_hash = Column(String(64), nullable=False)
    viewed_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class DownloadStat(Base):
    """Статистика скачиваний по IP-хешу (анти-накрутка)."""
    __tablename__ = "download_stats"
    __table_args__ = (
        Index("ix_download_stats_media_downloaded", "media_id", "downloaded_at"),
    )

    id = Column(Integer, primary_key=True)
    media_id = Column(Integer, ForeignKey("media.id", ondelete="CASCADE"), nullable=False)
    ip_hash = Column(String(64), nullable=False)
    downloaded_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class User(Base):
    """Пользователь: доступ к оригиналам (скачивание)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class UserSession(Base):
    """Сессия пользователя (cookie sid → sha256(token))."""
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)