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
    is_premium = Column(Boolean, nullable=False, default=False)     # контент только для премиум-пользователей
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

    # Гигиена обхода: сколько проходов каталога подряд тред отсутствовал
    # (misses) и с какого момента его нет в каталоге (missing_since).
    # Тред выключается (is_active=False) только после DEAD_THREAD_AFTER_MISSES
    # промахов: разовый обрыв каталога 2ch не гасит треды пачкой.
    misses = Column(Integer, nullable=False, default=0)
    missing_since = Column(DateTime, nullable=True)

    # Очередь докачки (двухфазный цикл: каталог всех досок → загрузка по очереди).
    # Фаза A помечает тред `pending_scan` (+причина), фаза B снимает флаг после
    # полного прохода. Очередь живёт в БД и переживает перезапуск процесса.
    pending_scan = Column(Boolean, nullable=False, default=False)
    pending_reason = Column(String(32), nullable=True)   # новый/изменения/просрочен/не скачивался/файлы
    last_scan_attempt_at = Column(DateTime, nullable=True)  # время последней попытки скана

    # Инкрементальный проход: номер последнего поста, полностью обработанного
    # «чистым» проходом — частые сканы смотрят только посты новее него.
    last_post_num = Column(Integer, nullable=True)
    # Сколько файлов упало в последнем проходе: >0 → следующий проход полный.
    last_scan_errors = Column(Integer, nullable=False, default=0)
    # Итог последнего прохода для админки (без чтения логов).
    last_scan_note = Column(String(255), nullable=True)

    # Управление из админки (этап: управление контентом)
    parse_enabled = Column(Boolean, nullable=False, default=False)  # тред участвует в скачивании
    is_visible = Column(Boolean, nullable=False, default=False)     # показывать публично
    is_premium = Column(Boolean, nullable=False, default=False)     # контент только для премиум-пользователей

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
    # Деривативы для оптимизации трафика: {"thumb": key, "thumb_blur": key, "web": key, "video": key}
    variants = Column(JSONB, nullable=True)
    duration_seconds = Column(Float, nullable=True)  # длительность видео (для бейджа)
    # Премиум-контент (денормализовано: доска ИЛИ тред); превью блюрится, полный — по подписке
    is_premium = Column(Boolean, nullable=False, default=False)

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
    # Метки пользователей («отличный контент», наш аналог лайка) — денормализованный счётчик
    marks_count = Column(Integer, nullable=False, default=0)
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
    # Кто смотрел (если был вход): по нему считается статистика по аккаунту
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
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
    # Кто скачал (скачивание доступно только премиум-подписке — всегда аккаунт)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    ip_hash = Column(String(64), nullable=False)
    downloaded_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class User(Base):
    """Пользователь: доступ к оригиналам (скачивание) и вход в админку."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    # Админ: вход в админку по email+паролю и восстановление пароля по почте
    is_admin = Column(Boolean, nullable=False, default=False)
    premium_until = Column(DateTime, nullable=True)  # премиум активен до этого времени
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AdminPasswordReset(Base):
    """Одноразовый токен восстановления пароля админа (в БД — только sha256).

    Живёт `ADMIN_RESET_TTL_MINUTES`; после успешной смены пароля помечается
    использованным, а все сессии пользователя удаляются.
    """
    __tablename__ = "admin_password_resets"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)


class UserSession(Base):
    """Сессия пользователя (cookie sid → sha256(token)).

    Хранит след входа для админки: хеш IP (сам IP не пишем), браузер и время
    последней активности. `last_seen_at` обновляется не чаще раза в несколько
    минут, поэтому запись на каждый запрос не делается.
    """

    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    ip_hash = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)
    last_seen_at = Column(DateTime, nullable=True, index=True)


class MediaMark(Base):
    """Метка пользователя на файле — «отличный контент» (наш аналог лайка).

    Единственная пользовательская отметка файла: и публичный счётчик
    (`media.marks_count`), и личный список «мои метки» (страница `/marks`).
    Требует аккаунт, ставится/снимается как переключатель.
    """
    __tablename__ = "media_marks"
    __table_args__ = (
        UniqueConstraint("user_id", "media_id", name="uq_media_marks_user_media"),
        Index("ix_media_marks_media", "media_id"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    media_id = Column(Integer, ForeignKey("media.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PageHit(Base):
    """Посещение сайта: просмотр страницы или событие в интерфейсе.

    Пишется с фронтенда (`POST /api/v1/hit`) — это «своя» аналитика: наружу
    ничего не уходит, IP не хранится (только sha256-хеш), реферер — только
    хостом, а браузер/ОС/устройство разбираются из User-Agent на бэкенде.

    * `kind = "page"` — просмотр страницы, `kind = "event"` — событие (`event`);
    * `session_id` — анонимный идентификатор из cookie `dv_sid` (30 дней);
    * `is_new_visit` — первое посещение в рамках визита (пауза > 30 мин).
    """

    __tablename__ = "page_hits"
    __table_args__ = (Index("ix_page_hits_kind_path", "kind", "path"),)

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    kind = Column(String(16), nullable=False, default="page")
    path = Column(String(255), nullable=False, default="/")
    event = Column(String(64), nullable=True)
    session_id = Column(String(40), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    ip_hash = Column(String(64), nullable=True)
    referrer_host = Column(String(120), nullable=True)
    utm_source = Column(String(80), nullable=True)
    device = Column(String(16), nullable=True)
    browser = Column(String(32), nullable=True)
    os = Column(String(32), nullable=True)
    is_bot = Column(Boolean, nullable=False, default=False)
    is_new_visit = Column(Boolean, nullable=False, default=False)


class AdminAudit(Base):
    """Аудит действий администратора: что и над чем меняли в админке."""

    __tablename__ = "admin_audit"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    actor = Column(String(255), nullable=True)   # email админа или "admin-token"
    action = Column(String(64), nullable=False)  # например user.premium, thread.delete
    target = Column(String(120), nullable=True)  # что изменили (id/слаг)
    details = Column(Text, nullable=True)        # короткая сводка изменений
    ip_hash = Column(String(64), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
