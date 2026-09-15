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
    # Ручной выбор превью для карточки каталога: id файлов этого раздела в нужном
    # порядке. Пусто/NULL — мозаика 2×2 собирается автоматически из 4 свежих файлов.
    cover_media_ids = Column(JSONB, nullable=True)
    # Источник, из которого берётся раздел (2ch.hk, slivach.com, …). Разные
    # источники парсятся разными адаптерами и независимыми прогонами.
    source_id = Column(
        Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )

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
    source = relationship("Source", back_populates="boards")


class ThreadState(Base):
    """Служебная таблица для инкрементального парсинга тредов."""
    __tablename__ = "threads_state"
    __table_args__ = (
        UniqueConstraint("board_id", "thread_id", name="uq_threads_state_board_thread"),
        # Внешний идентификатор «треда» у источника: у 2ch это номер треда,
        # у сайтов вроде slivach — слаг записи. Пара (доска, external_id) уникальна.
        UniqueConstraint("board_id", "external_id", name="uq_threads_state_board_external"),
    )

    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id", ondelete="CASCADE"), nullable=False)
    thread_id = Column(Integer, nullable=False)  # внутренний ID треда (у сайтов — синтетический)
    external_id = Column(String(64), nullable=False)  # внешний ID у источника (номер/слаг)
    # Отпечаток «треда» у источника: у сайтов нет ни постов, ни числа файлов,
    # зато есть своя метка изменения (например, имя обложки записи) — по ней
    # планировщик понимает, что запись обновилась, и ставит её в очередь.
    fingerprint = Column(String(120), nullable=True)

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
    # Денормализация источника (из доски) — фильтры админки по вкладкам источников
    source_id = Column(Integer, ForeignKey("sources.id", ondelete="SET NULL"), nullable=True, index=True)

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

    # Порядок файла внутри «треда» у источника (номер поста/файла: `post_num`).
    # Просмотр треда идёт «с начала», поэтому список сортируется по этому полю,
    # а не по времени скачивания: новые файлы всегда попадают в конец треда.
    source_order = Column(Integer, nullable=True)

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
    # Email необязателен: в модели Dredger 2.0 аккаунт заводит Telegram-бот, а вход
    # идёт по одноразовой ссылке (magic link). Пароль остаётся для админов и VIP.
    email = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    # Админ: вход в админку по email+паролю и восстановление пароля по почте
    is_admin = Column(Boolean, nullable=False, default=False)
    premium_until = Column(DateTime, nullable=True)  # премиум активен до этого времени
    # Telegram: аккаунт сайта = Telegram ID (пароль не нужен)
    telegram_id = Column(BigInteger, unique=True, nullable=True, index=True)
    telegram_username = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AuthMagicLink(Base):
    """Одноразовая ссылка входа (в БД хранится только sha256 токена).

    Выдаётся ботом (`/link`) или админом из карточки пользователя. Живёт
    `MAGIC_LINK_TTL_MINUTES`, после использования помечается `used_at` — повторно
    по той же ссылке войти нельзя.
    """

    __tablename__ = "auth_magic_links"

    id = Column(Integer, primary_key=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_ip = Column(String(64), nullable=True)


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


class UserResumePoint(Base):
    """Точка возврата «продолжить просмотр» для авторизованного зрителя.

    Анонимам точку хранит браузер (`localStorage`, `web/src/lib/resume.ts`).
    Для аккаунта она живёт здесь: сменил устройство — тред открывается на том же
    файле. Ключ — пара (пользователь, тред); `position` и `total` нужны, чтобы
    после выхода новых файлов по-прежнему считать «+N новых в конце», а если сам
    файл исчез из архива — вернуться по сохранённой позиции.
    """
    __tablename__ = "user_resume_points"
    __table_args__ = (
        UniqueConstraint("user_id", "thread_id", name="uq_user_resume_user_thread"),
        Index("ix_user_resume_user_updated", "user_id", "updated_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Тред — ключ точки: файлы внутри него меняются, а тред остаётся
    thread_id = Column(Integer, nullable=False)
    # Последний просмотренный файл (главный ориентир)
    media_id = Column(Integer, nullable=False)
    # Позиция файла в списке треда (0-based) и полный размер треда на момент просмотра
    position = Column(Integer, nullable=False, default=0)
    total = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


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


class Feedback(Base):
    """Обращение посетителя: идея, баг, запрос премиум-доступа, вопрос по контенту.

    Пишется из формы `/feedback` (в том числе анонимно — тогда сохраняем
    контактный email, если его указали). Ответ администратора — в поле
    `admin_note`, статус ведёт приёмную в админке.
    """

    __tablename__ = "feedback"
    __table_args__ = (Index("ix_feedback_status_created", "status", "created_at"),)

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    topic = Column(String(24), nullable=False, default="other")  # bug|idea|premium|content|other
    message = Column(Text, nullable=False)
    email = Column(String(255), nullable=True)          # контакт для ответа (может не быть)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    page_url = Column(String(255), nullable=True)       # откуда написали
    ip_hash = Column(String(64), nullable=True)
    status = Column(String(16), nullable=False, default="new")  # new|in_progress|answered|closed
    admin_note = Column(Text, nullable=True)            # ответ/заметка администратора
    answered_at = Column(DateTime, nullable=True)


class Source(Base):
    """Источник контента для парсинга (2ch.hk, slivach.com, …).

    Каждый источник — отдельный адаптер и **свой независимый прогон**: свои
    флаги запуска в Redis (`parser:{code}:enabled` и т.д.), своё расписание,
    вежливость к сайту и бюджет цикла, своя история в `parse_runs`. Доски и
    файлы привязаны к источнику, поэтому контент в админке разделяется по
    вкладкам источников, а падение/пауза одного не затрагивает другой.
    """

    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, nullable=False)      # dvach | slivach
    title = Column(String(100), nullable=False, default="")
    kind = Column(String(32), nullable=False, default="json")   # адаптер: json | html
    base_url = Column(String(255), nullable=False, default="")
    # Настройки адаптера (категории, пагинация, заголовки, лимиты, отбор записей):
    # добавление источника = запись + адаптер, без миграций под каждый сайт.
    config = Column(JSONB, nullable=False, default=dict)
    is_enabled = Column(Boolean, nullable=False, default=False)      # участвует в прогонах
    schedule_minutes = Column(Integer, nullable=False, default=30)   # период цикла
    rate_limit_rps = Column(Float, nullable=False, default=1.0)      # запросов в секунду к сайту
    budget_minutes = Column(Integer, nullable=False, default=30)     # бюджет одного прогона
    sort_order = Column(Integer, nullable=False, default=0)          # порядок в админке/очереди

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    boards = relationship("Board", back_populates="source", passive_deletes=True)
    runs = relationship("ParseRun", back_populates="source", passive_deletes=True)


class ParseRun(Base):
    """История прогонов источника: что и когда парсили и с каким результатом.

    Прогресс «прямо сейчас» живёт в Redis (`parser:{code}:progress`, TTL),
    а итог каждого цикла пишется сюда — он переживает перезапуск контейнера и
    показывается в админке во вкладке источника.
    """

    __tablename__ = "parse_runs"
    __table_args__ = (
        Index("ix_parse_runs_source_started", "source_id", "started_at"),
    )

    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    # running | ok | error | stopped — «stopped» это ручная остановка из админки
    status = Column(String(16), nullable=False, default="running")
    phase = Column(String(32), nullable=True)   # catalog | files | done
    # Сводка прогона: доски/категории, треды, файлы, байты, ошибки, длительность
    stats = Column(JSONB, nullable=False, default=dict)
    error = Column(Text, nullable=True)

    source = relationship("Source", back_populates="runs")


class MediaReport(Base):
    """Жалоба на файл: модерация и требования правообладателей.

    Жалобу пишет вошедший зритель (кнопка «Пожаловаться» в лайтбоксе и на
    странице файла). Открытая жалоба у пары (пользователь, файл) одна: повторная
    отправка обновляет причину и комментарий. Разбор — в админке
    (`/admin/reports`): файл скрывают, скрывают тред, удаляют файл вместе с
    объектом в S3 или жалобу отклоняют. Каждое действие пишется в `admin_audit`.

    Жалоба с причиной `csam` закрывает доступ сразу: файл и тред скрываются
    автоматически, до ручного разбора (контент не должен ждать модератора).
    """

    __tablename__ = "media_reports"
    __table_args__ = (
        Index("ix_media_reports_status_created", "status", "created_at"),
        Index("ix_media_reports_media", "media_id"),
    )

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    media_id = Column(Integer, ForeignKey("media.id", ondelete="CASCADE"), nullable=False)
    # Аккаунт может быть удалён — жалоба остаётся как история модерации
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # csam | copyright | illegal | spam | other
    reason = Column(String(24), nullable=False, default="other")
    comment = Column(Text, nullable=True)
    # open | hidden | thread_hidden | removed | rejected
    status = Column(String(16), nullable=False, default="open")
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolution_note = Column(Text, nullable=True)
    ip_hash = Column(String(64), nullable=True)


class TelegramPost(Base):
    """Пост в Telegram-канале: заготовка, публикация и журнал отправки.

    Модель Dredger 2.0: канал — витрина, весь архив за логином. Поэтому пост ведёт
    в бота (`t.me/<bot>?start=…`), а не на сайт, и собирается из наших же превью
    (мозаика 2×2) с размытием — канал не должен ловить блокировку за adult-контент.

    `scheduled_at` пока не используется: публикация ручная (композер в админке),
    поле оставлено под следующий шаг — планировщик публикаций.
    """

    __tablename__ = "telegram_posts"
    __table_args__ = (
        Index("ix_telegram_posts_created", "created_at"),
        Index("ix_telegram_posts_status_scheduled", "status", "scheduled_at"),
    )

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)
    # teaser | digest | announce — от типа зависит шаблон подписи
    kind = Column(String(16), nullable=False, default="teaser")
    caption = Column(Text, nullable=False, default="")
    # Выбранные файлы: id из `media` (порядок плиток мозаики сохраняем)
    media_ids = Column(JSONB, nullable=True)
    image_mode = Column(String(12), nullable=False, default="mosaic")  # mosaic | single | none
    button_text = Column(String(64), nullable=True)
    button_url = Column(String(255), nullable=True)
    # draft | published | failed
    status = Column(String(16), nullable=False, default="draft")
    channel = Column(String(120), nullable=True)
    message_id = Column(BigInteger, nullable=True)   # id сообщения канала (ссылка/удаление)
    error = Column(Text, nullable=True)
    created_by = Column(String(120), nullable=True)  # админ-актор, собравший пост
    scheduled_at = Column(DateTime, nullable=True)   # резерв под расписание публикаций


class TelegramAutopost(Base):
    """Настройки автопостинга в канал (одна строка, id=1).

    Модель Dredger 2.0: канал получает 1–3 поста в день без «шума». Поэтому у
    автопостинга есть лимит, окна тишины и белый список разделов, а по умолчанию
    включён режим карантина (`require_approval`): черновик приходит админу в ЛС бота
    с кнопками «Опубликовать / Отклонить / Отложить» — в канал ничего не уходит само.
    """

    __tablename__ = "telegram_autopost"

    id = Column(Integer, primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False)
    # Сколько постов в сутки и в какие часы молчим (МСК)
    posts_per_day = Column(Integer, nullable=False, default=2)
    quiet_from = Column(Integer, nullable=False, default=1)   # час МСК
    quiet_to = Column(Integer, nullable=False, default=8)
    # Карантин: без подтверждения админа в ЛС постов в канал нет
    require_approval = Column(Boolean, nullable=False, default=True)
    # Белый список разделов (слаги) и период дайджеста: day | week
    boards = Column(JSONB, nullable=True)
    period = Column(String(8), nullable=False, default="day")
    blur = Column(Integer, nullable=False, default=7)
    last_check_at = Column(DateTime, nullable=True)   # когда воркер последний раз работал
    last_post_at = Column(DateTime, nullable=True)    # когда автопост уходил в канал
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class Giveaway(Base):
    """Розыгрыш премиум-подписки: ежедневный или еженедельный.

    Участие — через бота с проверкой подписки на канал (ссылка приходит в посте-анонсе
    с deep-link `start=giveaway_<id>`). Победителю премиум выдаётся автоматически,
    как и при ручной выдаче в админке: продлеваем `premium_until` на `prize_days`.
    """

    __tablename__ = "giveaways"
    __table_args__ = (Index("ix_giveaways_status_ends", "status", "ends_at"),)

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    title = Column(String(120), nullable=False, default="")
    # daily | weekly
    kind = Column(String(12), nullable=False, default="daily")
    prize_days = Column(Integer, nullable=False, default=3)
    starts_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ends_at = Column(DateTime, nullable=False)
    # draft | announced | drawn | cancelled
    status = Column(String(16), nullable=False, default="draft")
    # Победители: [{user_id, telegram_id, username}]
    winners = Column(JSONB, nullable=True)
    # Сообщения канала: анонс и итоги (для ссылок в админке)
    announce_message_id = Column(BigInteger, nullable=True)
    result_message_id = Column(BigInteger, nullable=True)
    created_by = Column(String(120), nullable=True)


class GiveawayEntry(Base):
    """Участник розыгрыша: один аккаунт — одно участие."""

    __tablename__ = "giveaway_entries"
    __table_args__ = (
        UniqueConstraint("giveaway_id", "user_id", name="uq_giveaway_entries_user"),
        Index("ix_giveaway_entries_giveaway", "giveaway_id"),
    )

    id = Column(Integer, primary_key=True)
    giveaway_id = Column(Integer, ForeignKey("giveaways.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    telegram_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Plan(Base):
    """Тариф подписки: неделя / месяц / год / навсегда.

    Модель доступа «открытый архив»: Free видит только открытые разделы (и получает
    рекламу), Premium открывает приватные разделы, скачивание и убирает рекламу.

    Цена хранится в рублях — для крипты пересчитывается по курсу на момент счёта,
    поэтому «цена в тарифе» остаётся понятной человеку и не зависит от валюты.
    """

    __tablename__ = "plans"

    code = Column(String(16), primary_key=True)      # week | month | year | forever
    title = Column(String(64), nullable=False)
    description = Column(String(200), nullable=False, default="")
    days = Column(Integer, nullable=False)           # сколько дней доступа даёт тариф
    price_rub = Column(Integer, nullable=False)
    # Цена в звёздах Telegram (вариант A: задаётся вручную). NULL — оплата звёздами
    # для этого тарифа недоступна.
    price_stars = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    badge = Column(String(32), nullable=True)        # «выгодно», «хит» и т. п.
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Promo(Base):
    """Акция: скидка на тарифы, которую включают вручную под событие.

    Раньше акция была одна и «стартовая»; теперь их может быть сколько угодно
    (запуск, праздник, «первым 50 оплат», акция только на год и т. п.). Условия
    (название, описание, процент, срок, лимит) задаются в админке, а `is_active`
    решает, показывать ли акцию покупателям — включить её можно к любому событию.

    Скидка применяется и к рублёвой цене, и к цене в звёздах: процент один, поэтому
    витрина, бот и счёт всегда согласованы.
    """

    __tablename__ = "promos"
    __table_args__ = (Index("ix_promos_active", "is_active", "ends_at"),)

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    title = Column(String(64), nullable=False)
    description = Column(String(200), nullable=False, default="")
    percent = Column(Integer, nullable=False, default=50)
    # Включение вручную: акцию заводят заранее и включают к событию
    is_active = Column(Boolean, nullable=False, default=False)
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    max_paid = Column(Integer, nullable=True)        # лимит оплат по акции
    # На какие тарифы действует (["week", ...]); NULL — на все
    applies_to = Column(JSONB, nullable=True)


class Payment(Base):
    """Журнал платежей: ручная выдача, CryptoBot (позже — Stars).

    Нужен и для истории, и для акции: «до первых 50 платящих» считаем по статусу
    `paid`. Выдача премиума идемпотентна по `external_id` — вебхук/поллинг платежа
    не должен продлить подписку дважды.
    """

    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_user", "user_id"),
        Index("ix_payments_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    plan_code = Column(String(16), nullable=False)
    # Сколько заплачено: с учётом скидки — эту сумму видит человек в счёте
    amount_rub = Column(Integer, nullable=False, default=0)
    discount_percent = Column(Integer, nullable=False, default=0)
    # manual | cryptobot | stars
    provider = Column(String(16), nullable=False, default="manual")
    external_id = Column(String(64), nullable=True)
    # pending | paid | cancelled | failed | refunded
    status = Column(String(16), nullable=False, default="pending")
    days = Column(Integer, nullable=False, default=0)
    premium_until = Column(DateTime, nullable=True)
    note = Column(String(200), nullable=True)


class BlockedHash(Base):
    """Блок-лист хешей файлов (запрещённый контент, в первую очередь CSAM).

    Файл, чей SHA-256 попал в список, не публикуется: существующие записи
    скрываются сразу при добавлении хеша, а новые пайплайн сохраняет скрытыми
    (`is_visible=False`) — см. `src/services/pipeline.py`. Список ведётся в
    админке (вкладка жалоб) и пополняется вручную или автоскрытием по жалобе.
    """

    __tablename__ = "blocked_hashes"

    id = Column(Integer, primary_key=True)
    sha256 = Column(String(64), unique=True, nullable=False)
    reason = Column(String(32), nullable=False, default="other")  # csam | copyright | other
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_by = Column(String(120), nullable=True)
