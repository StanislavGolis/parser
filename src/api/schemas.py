# src/api/schemas.py
"""Pydantic-схемы ответов API."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class BoardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    description: Optional[str] = None
    media_count: int = 0
    is_premium: bool = False
    # Премиум-контент, но подписки у зрителя нет (превью размыто)
    locked: bool = False
    # До 4 свежих превью раздела — мозаика 2×2 на карточке каталога
    cover_thumbs: List[str] = []


class AdminBoardOut(BoardOut):
    """Доска в админке: флаги управления и живая статистика контента."""
    parse_enabled: bool = True
    is_visible: bool = True
    sort_order: int = 0
    parse_mode: str = "all"  # all | selected

    # Статистика (агрегируется из БД)
    media_total: int = 0
    media_downloaded: int = 0
    media_in_s3: int = 0
    media_missing: int = 0
    threads_active: int = 0
    threads_parsing: int = 0
    threads_pending: int = 0  # треды в очереди на докачку (pending_scan)
    threads_dead: int = 0     # треды, выпавшие из каталога форума
    files_in_catalog: int = 0
    threads_posts_total: int = 0
    threads_views_total: int = 0
    last_scan: Optional[datetime] = None
    views_total: int = 0
    downloads_total: int = 0
    # Каталог доски недоступен (2ch вернул 500/404 — раздел удалён): текст причины
    catalog_error: Optional[str] = None


class SystemTotals(BaseModel):
    boards_total: int = 0
    boards_parsed: int = 0
    media_total: int = 0
    media_in_s3: int = 0
    media_downloaded: int = 0
    media_missing: int = 0
    threads_active: int = 0
    threads_parsing: int = 0
    threads_pending: int = 0
    threads_dead: int = 0
    files_in_catalog: int = 0
    threads_posts_total: int = 0
    threads_views_total: int = 0
    views_total: int = 0
    downloads_total: int = 0


class AdminOverview(BaseModel):
    """Снапшот для админ-панели (обновляется polling'ом)."""
    generated_at: datetime
    totals: SystemTotals
    boards: List[AdminBoardOut]
    parser_up: bool = False          # демон парсера запущен (heartbeat parser:up)
    parser_enabled: bool = False     # парсинг включён (parser:enabled)
    parser_alive: bool = False       # парсер прямо сейчас активно работает
    parser_current_board: Optional[str] = None


class ForumBoardOut(BaseModel):
    """Доска форума (из index.json двача), сопоставленная с нашей БД."""
    slug: str
    name: Optional[str] = None
    category: Optional[str] = None
    threads_on_forum: int = 0
    in_db: bool = False
    parse_enabled: bool = False
    is_visible: bool = False
    is_premium: bool = False
    media_total: int = 0
    media_in_s3: int = 0
    threads_active: int = 0


class AdminLoginIn(BaseModel):
    """Вход в админку по email+паролю (админ-аккаунт)."""
    email: str
    password: str


class AdminLoginOut(BaseModel):
    """Успешный вход: панель получает тот же токен, что лежит в .env."""
    email: str
    token: str


class AdminForgotIn(BaseModel):
    """Запрос ссылки восстановления пароля."""
    email: str


class AdminForgotOut(BaseModel):
    sent: bool              # попытка отправки сделана (SMTP настроен)
    smtp_configured: bool   # настроена ли почта вообще
    detail: str = ""        # текст для интерфейса


class AdminResetIn(BaseModel):
    """Сброс пароля по одноразовой ссылке из письма."""
    token: str
    password: str = Field(min_length=10, max_length=128)


class AdminResetOut(BaseModel):
    email: str
    ok: bool = True


class StatusOut(BaseModel):
    """Публичная сводка архива для главной страницы (только цифры о контенте)."""
    files_total: int
    files_24h: int
    threads_active: int
    boards_visible: int


class BoardCreate(BaseModel):
    slug: str
    name: Optional[str] = None  # настоящее название (из index.json), если известно
    # Добавить, даже если каталог раздела сейчас не читается (2ch отдаёт 500 для
    # закрытых/удалённых разделов). Такой раздел появится в списке с бейджем
    # «каталог недоступен» и не будет парситься, пока форум его не откроет.
    force: bool = False


class BoardUpdate(BaseModel):
    parse_enabled: Optional[bool] = None
    is_visible: Optional[bool] = None
    is_premium: Optional[bool] = None
    parse_mode: Optional[str] = None  # all | selected
    title: Optional[str] = None


class ThreadUpdate(BaseModel):
    """Флаги треда: парсинг, публикация и премиум-доступ."""
    parse_enabled: Optional[bool] = None
    is_visible: Optional[bool] = None
    is_premium: Optional[bool] = None
    # «Вернуть в обход»: тред выпал из каталога доски, вернуть его в работу
    # (is_active=True, сброс промахов каталога)
    restore: Optional[bool] = None
    # «В очередь»: вручную поставить тред в очередь докачки (pending_scan)
    requeue: Optional[bool] = None


class ThreadBulkUpdate(BaseModel):
    """Массовое изменение флагов выбранных тредов одной доски."""
    thread_ids: List[int]
    parse_enabled: Optional[bool] = None
    is_visible: Optional[bool] = None
    is_premium: Optional[bool] = None
    restore: Optional[bool] = None  # вернуть в обход (is_active=True, misses=0)
    requeue: Optional[bool] = None  # поставить в очередь докачки (pending_scan)


class BoardReorder(BaseModel):
    """Новый порядок парсинга: слаги досок в требуемой последовательности."""
    slugs: List[str]


class ResetResult(BaseModel):
    deleted_boards: int = 0
    deleted_objects: int = 0


class ThreadDeleteRequest(BaseModel):
    """Какие треды раздела удалить вместе с файлами в хранилище."""

    thread_ids: List[int] = []


class ThreadDeleteResult(BaseModel):
    """Итог удаления тредов: треды, записи файлов и объекты в S3."""

    deleted_threads: int = 0
    deleted_media: int = 0
    deleted_objects: int = 0
    # Объекты, которые остались: на них ссылаются файлы других тредов
    kept_objects: int = 0
    # Предпросмотр: цифры посчитаны, ничего не удалено
    dry_run: bool = False


class AuthCredentials(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    premium_until: Optional[datetime] = None
    is_premium: bool = False  # премиум активен прямо сейчас
    marks_count: int = 0      # сколько меток поставил пользователь («мои метки»)


class MarkResult(BaseModel):
    """Результат переключения метки («отличный контент»)."""
    media_id: int
    marked: bool       # стоит ли метка теперь
    marks_count: int   # всего меток у файла


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    board_id: int
    thread_id: int
    original_name: str
    file_size: int
    mime_type: str
    media_type: str
    width: Optional[int] = None
    height: Optional[int] = None
    views_count: int
    downloads_count: int
    popularity_score: float
    created_at: datetime
    # Технические данные (для техпанели lightbox)
    source_md5: Optional[str] = None
    file_hash: Optional[str] = None
    url: Optional[str] = None        # оригинал (/media/{id}/raw)
    thumb_url: Optional[str] = None  # превью-дериватив (/media/{id}/asset/thumb|thumb_blur)
    # Размытый плейсхолдер (blur-up): показывается, пока грузится превью
    blur_url: Optional[str] = None
    web_url: Optional[str] = None    # оптимизированная версия (/media/{id}/asset/web)
    duration_seconds: Optional[float] = None  # длительность видео
    # Премиум-контент: locked=True — нужна подписка (превью размыто, полный недоступен)
    is_premium: bool = False
    locked: bool = False
    # Метка «отличный контент» (аналог лайка) — публичный счётчик и личный список
    marks_count: int = 0          # сколько пользователей отметили файл
    marked: bool = False          # отметил ли текущий пользователь


class MediaListOut(BaseModel):
    items: List[MediaOut]
    page: int
    per_page: int
    total: int


class ThreadOut(BaseModel):
    """Тред доски с агрегированной статистикой файлов (для сайта/админки)."""
    model_config = ConfigDict(from_attributes=True)

    board_id: int
    thread_id: int
    subject: Optional[str] = None
    comment: Optional[str] = None
    posts_count: int = 0
    files_count: int = 0          # счётчик каталога 2ch (постов с вложениями, не файлов)
    files_detected: int = 0       # файлов в треде по res/{id}.json (до загрузки)
    views_count: int = 0          # просмотров треда (из каталога)
    thread_timestamp: Optional[datetime] = None
    last_scanned_at: Optional[datetime] = None
    is_active: bool = True
    # Гигиена обхода (админка): промахи каталога, дата исчезновения, «просрочен»
    misses: int = 0                            # проходов каталога подряд без треда
    missing_since: Optional[datetime] = None   # когда тред впервые выпал из каталога
    is_stale: bool = False                     # «Парсить» включён, но давно не сканировался
    # Очередь докачки: тред ждёт скана, причина («новый»/«изменения»/«просрочен»/…)
    pending_scan: bool = False
    pending_reason: Optional[str] = None
    last_scan_attempt_at: Optional[datetime] = None
    # Итог последнего прохода: до какого поста обработано, сколько ошибок, сводка
    last_post_num: Optional[int] = None
    last_scan_errors: int = 0
    last_scan_note: Optional[str] = None

    # Управление (админка) и премиум-доступ
    parse_enabled: bool = True
    is_visible: bool = True
    is_premium: bool = False
    # Премиум-тред (с учётом премиума доски), но подписки у зрителя нет
    locked: bool = False

    # Статистика по файлам из нашей БД
    media_total: int = 0          # всего записей в БД
    media_downloaded: int = 0     # скачано (без выгрузки в S3)
    media_in_s3: int = 0          # загружено в S3 (uploaded+verified)
    media_missing: int = 0        # файл потерян
    media_visible: int = 0        # видимых на сайте

    # Несколько последних файлов треда для превью
    preview: List[MediaOut] = []


class ThreadListOut(BaseModel):
    items: List[ThreadOut]
    page: int
    per_page: int
    total: int
    # Счётчики по состояниям (для чипов фильтра в админке)
    counts: Optional[dict] = None
    # Суммы по доске (описание страницы сканирования):
    # посты/просмотры/файлы-на-форуме — из каталога и res/{id}.json; скачано — из БД
    posts_total: int = 0
    views_total: int = 0
    files_detected_total: int = 0
    files_downloaded_total: int = 0


class MediaDetailOut(MediaOut):
    board_slug: Optional[str] = None
    duplicate_of_id: Optional[int] = None


class ViewResult(BaseModel):
    media_id: int
    counted: bool         # True — счётчик увеличен, False — дубль за период


class DownloadResult(BaseModel):
    media_id: int
    counted: bool
    url: str


class TopItem(MediaOut):
    pass


class ToggleResult(BaseModel):
    id: int
    is_visible: bool