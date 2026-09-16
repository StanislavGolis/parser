# src/api/schemas.py
"""Pydantic-схемы ответов API."""
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class BoardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    description: Optional[str] = None
    media_count: int = 0
    # Сколько файлов прибавилось за текущие отчётные сутки (МСК): «+N за сегодня»
    media_today: int = 0
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
    # Источник раздела: по нему админка раскладывает доски по вкладкам источников
    source_id: Optional[int] = None
    # Ручные превью карточки раздела: id файлов в порядке плиток (пусто — авто)
    cover_media_ids: List[int] = []

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


class SourceBoardOut(BaseModel):
    """Раздел источника (аналог «доски форума») в сопоставлении с нашей БД.

    Так админка показывает, что источник вообще предлагает: 2ch — доски из
    `index.json`, сайт — свои категории. Пользователь выбирает из списка и
    добавляет разделы в систему (`POST /admin/boards`).
    """
    slug: str
    name: Optional[str] = None
    group: Optional[str] = None      # рубрика источника (категория доски на 2ch)
    hint: int = 0                    # сколько «тредов» источник показывает (оценка)
    in_db: bool = False
    parse_enabled: bool = False
    parse_mode: Optional[str] = None
    is_visible: bool = False
    is_premium: bool = False
    media_total: int = 0
    media_in_s3: int = 0
    threads_active: int = 0


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
    """Публичная сводка архива для главной страницы (только цифры о контенте).

    «За сутки» — это отчётные сутки по МСК (00:00–24:00), см. `services/reporting`:
    тот же период используется в админке, на карточках разделов и в письме-отчёте.
    """
    files_total: int
    files_today: int = 0
    threads_active: int
    boards_visible: int
    # Границы отчётного периода: ISO (UTC, как в БД) и подпись для интерфейса
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    period_label: str = ""


class BoardCreate(BaseModel):
    slug: str
    name: Optional[str] = None  # настоящее название (из index.json), если известно
    # Источник, к которому относится раздел: `dvach` (по умолчанию) или другой
    # код из реестра источников. Для 2ch проверяем каталог раздела, для
    # остальных источников доски создаёт их собственный парсер.
    source: str = "dvach"
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
    # Текст раздела для сайта: показывается под заголовком и уходит в мета-описание
    # (JSON-LD CollectionPage, description страницы). Пустая строка очищает текст.
    description: Optional[str] = None
    # Ручные превью карточки раздела: до 4 id файлов этого же раздела, в нужном
    # порядке. Пустой список — вернуть автоматический выбор (4 свежих файла).
    cover_media_ids: Optional[List[int]] = None


class BoardCoverCandidate(BaseModel):
    """Файл-кандидат для ручного превью раздела (галерея в админке)."""

    id: int
    media_type: str = "image"
    thumb_url: Optional[str] = None


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


class SourceUpdate(BaseModel):
    """Правка источника в реестре (вкладка «Источники» в админке).

    Все поля необязательные: приходит только то, что меняли. `config` — настройки
    адаптера (категории, селекторы, пагинация, заголовки) для сайтов-источников.
    """

    title: Optional[str] = None
    base_url: Optional[str] = None
    is_enabled: Optional[bool] = None
    schedule_minutes: Optional[int] = None
    rate_limit_rps: Optional[float] = None
    budget_minutes: Optional[int] = None
    sort_order: Optional[int] = None
    config: Optional[Dict[str, object]] = None


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
    # У аккаунтов из Telegram почты нет — поэтому поле необязательное, а имя
    # для интерфейса собирается в `display_name` (email → @ник → Telegram ID)
    email: Optional[str] = None
    display_name: str = ""
    telegram_id: Optional[int] = None
    telegram_username: Optional[str] = None
    premium_until: Optional[datetime] = None
    is_premium: bool = False  # премиум активен прямо сейчас
    marks_count: int = 0      # сколько меток поставил пользователь («мои метки»)
    created_at: Optional[datetime] = None  # дата регистрации («с нами с …»)


class MarkResult(BaseModel):
    """Результат переключения метки («отличный контент»)."""
    media_id: int
    marked: bool       # стоит ли метка теперь
    marks_count: int   # всего меток у файла


class FeedbackIn(BaseModel):
    """Обращение из формы обратной связи (в том числе анонимно)."""
    topic: str = "other"            # bug | idea | premium | content | other
    message: str
    email: Optional[str] = None     # контакт для ответа (может не быть)
    page_url: Optional[str] = None  # откуда написали
    website: Optional[str] = None   # ловушка для ботов: люди это поле не видят


class FeedbackOut(BaseModel):
    """Обращение для админки: текст, контакт, статус и заметка-ответ."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    topic: str
    topic_label: Optional[str] = None
    message: str
    email: Optional[str] = None
    page_url: Optional[str] = None
    user_id: Optional[int] = None
    status: str = "new"
    admin_note: Optional[str] = None
    answered_at: Optional[datetime] = None


class FeedbackListOut(BaseModel):
    items: List[FeedbackOut]
    total: int
    # Сколько заявок в каждом статусе — цифры на чипах-фильтрах админки
    counts: Dict[str, int] = {}


class FeedbackUpdate(BaseModel):
    """Что админ может поменять у обращения."""
    status: Optional[str] = None   # new | in_progress | answered | closed
    admin_note: Optional[str] = None


class MediaReportIn(BaseModel):
    """Жалоба на файл с сайта (кнопка «Пожаловаться»)."""

    reason: str = "other"           # csam | copyright | illegal | spam | other
    comment: Optional[str] = None
    page_url: Optional[str] = None


class MediaReportOut(BaseModel):
    """Жалоба для админки: файл, автор, причина и результат разбора."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    media_id: int
    user_id: Optional[int] = None
    reason: str
    reason_label: Optional[str] = None
    comment: Optional[str] = None
    status: str = "open"
    resolved_at: Optional[datetime] = None
    resolution_note: Optional[str] = None

    # Контекст файла: админу нужно видеть, на что именно пожаловались
    media_name: Optional[str] = None
    board_slug: Optional[str] = None
    thread_id: Optional[int] = None
    media_type: Optional[str] = None
    thumb_url: Optional[str] = None
    media_visible: Optional[bool] = None
    # Кто пожаловался: email или @ник в Telegram
    reporter: Optional[str] = None


class MediaReportListOut(BaseModel):
    items: List[MediaReportOut]
    total: int
    # Сколько жалоб в каждом статусе — цифры на чипах-фильтрах админки
    counts: Dict[str, int] = {}


class MediaReportUpdate(BaseModel):
    """Решение модератора по жалобе."""

    action: str                     # hide_media | hide_thread | remove_media | reject
    note: Optional[str] = None


class BlockedHashIn(BaseModel):
    """Добавление хеша в блок-лист (CSAM и прочий запрещённый контент)."""

    sha256: str
    reason: str = "csam"            # csam | copyright | other
    note: Optional[str] = None


class BlockedHashOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sha256: str
    reason: str
    note: Optional[str] = None
    created_at: datetime
    created_by: Optional[str] = None
    # Сколько файлов архива уже скрыто этим хешем
    media_count: int = 0


class TelegramPostIn(BaseModel):
    """Заготовка поста в канал: тип, текст, файлы и режим картинки."""

    kind: str = "teaser"            # teaser | digest | announce
    text: Optional[str] = None      # свободный текст (для анонсов)
    media_ids: List[int] = []
    image_mode: str = "mosaic"      # mosaic | single | none
    blur: int = 7                   # размытие картинки: канал должен быть «мягким»
    button_text: Optional[str] = None
    button_url: Optional[str] = None
    period: Optional[str] = None    # day | week — для дайджеста
    scheduled_at: Optional[datetime] = None  # задано → пост уходит в очередь


class TelegramAutopostIn(BaseModel):
    """Настройки автопостинга: что приходит только нужное и не ночью."""

    enabled: Optional[bool] = None
    posts_per_day: Optional[int] = None
    quiet_from: Optional[int] = None
    quiet_to: Optional[int] = None
    require_approval: Optional[bool] = None
    boards: Optional[List[str]] = None
    period: Optional[str] = None
    blur: Optional[int] = None


class TelegramAutopostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool = False
    posts_per_day: int = 2
    quiet_from: int = 1
    quiet_to: int = 8
    require_approval: bool = True
    boards: Optional[List[str]] = None
    period: str = "day"
    blur: int = 7
    last_check_at: Optional[datetime] = None
    last_post_at: Optional[datetime] = None
    # Сколько постов уже ушло за сутки и можно ли запускать автопост сейчас
    published_last_day: int = 0
    allowed: bool = False
    reason: Optional[str] = None


class TelegramRubricIn(BaseModel):
    """Правка рубрики автопоста: включение, пауза между постами и параметры."""

    enabled: Optional[bool] = None
    title: Optional[str] = None
    sort_order: Optional[int] = None
    min_gap_hours: Optional[int] = None
    # Параметры рубрики (blur, tiles, boards_count, board_photos, board, sort…).
    # Присланные ключи перекрывают сохранённые; пустая строка/None удаляет ключ.
    options: Optional[Dict[str, object]] = None


class TelegramRubricOut(BaseModel):
    """Рубрика в админке: что настроено и когда выходила в последний раз."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    title: str = ""
    enabled: bool = False
    sort_order: int = 0
    min_gap_hours: int = 24
    options: Optional[Dict[str, object]] = None
    # Значения по умолчанию, наложенные на сохранённые: что применится при сборке
    effective: Dict[str, object] = {}
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    can_run: bool = False
    reason: Optional[str] = None


class TelegramRubricPreviewOut(BaseModel):
    """Предпросмотр рубрики: текст, кадры (data URL) и какие файлы попали в пост."""

    code: str
    caption: str = ""
    image_mode: str = "none"
    images: List[str] = []
    media_ids: List[int] = []
    boards: List[str] = []
    board: str = ""
    tiles: List[int] = []
    photos: List[int] = []
    note: Optional[str] = None


class TelegramDigestOut(BaseModel):
    """Готовая подборка для дайджеста: файлы и подпись (без отправки)."""

    media_ids: List[int] = []
    boards: List[str] = []
    caption: str = ""
    period: str = "day"


class GiveawayIn(BaseModel):
    """Новый розыгрыш: тип, приз и срок."""

    kind: str = "daily"             # daily | weekly
    prize_days: int = 3
    title: Optional[str] = None
    hours: Optional[int] = None     # свой срок в часах (для тестовых прогонов)


class GiveawayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    title: str
    kind: str
    prize_days: int
    starts_at: datetime
    ends_at: datetime
    status: str
    winners: Optional[List[dict]] = None
    entries: int = 0                # сколько участников
    link: Optional[str] = None      # ссылка на анонс в канале


class TelegramPostOut(BaseModel):
    """Запись журнала: что публиковали, когда и с каким результатом."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    published_at: Optional[datetime] = None
    kind: str
    caption: str
    media_ids: Optional[List[int]] = None
    image_mode: str = "mosaic"
    status: str                    # draft | published | failed | deleted
    channel: Optional[str] = None
    message_id: Optional[int] = None
    error: Optional[str] = None
    created_by: Optional[str] = None
    # Ссылка на сообщение в канале (если опубликовано)
    link: Optional[str] = None
    # Для отложенных: когда пост выйдет (планировщик `telegram-publisher`)
    scheduled_at: Optional[datetime] = None
    # Рубрика автопоста (fresh | board_day | top_week); у ручных постов пусто
    rubric: Optional[str] = None


class TelegramPostListOut(BaseModel):
    items: List[TelegramPostOut]
    total: int
    counts: Dict[str, int] = {}


class TelegramPreviewOut(BaseModel):
    """Предпросмотр поста: текст и картинка (без публикации)."""

    caption: str
    image_data_url: Optional[str] = None
    chat: Optional[str] = None
    configured: bool = False
    warning: Optional[str] = None


class TelegramCandidateOut(BaseModel):
    """Файл-кандидат для тизера (галерея выбора в админке)."""

    id: int
    media_type: str = "image"
    thumb_url: Optional[str] = None
    board_slug: Optional[str] = None


class PlanPriceOut(BaseModel):
    """Тариф на витрине: цена в рублях, цена в звёздах и скидка, если акция идёт."""

    code: str
    title: str
    description: str = ""
    days: int
    price_rub: int
    price_now: int
    # Звёзды Telegram: цена задаётся вручную, None — оплата звёздами выключена
    price_stars: Optional[int] = None
    stars_now: Optional[int] = None
    # Крипта (Crypto Pay): цена в центах USDT, None — оплата криптой выключена
    price_usdt_cents: Optional[int] = None
    usdt_now_cents: Optional[int] = None
    discount_percent: int = 0
    promo_id: Optional[int] = None
    promo_title: Optional[str] = None
    promo_description: Optional[str] = None
    badge: Optional[str] = None
    is_forever: bool = False


class PromoOut(BaseModel):
    """Акция: название, описание, процент и состояние (идёт ли, сколько осталось)."""

    id: int
    title: str
    description: str = ""
    percent: int
    is_active: bool = False
    active: bool = False
    reason: str = ""
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    days_left: Optional[int] = None
    max_paid: Optional[int] = None
    paid_left: Optional[int] = None
    # Пустой список — акция на все тарифы
    applies_to: List[str] = []


class PlansOut(BaseModel):
    """Витрина тарифов: то, что показывают сайт и бот."""

    plans: List[PlanPriceOut]
    promos: List[PromoOut] = []


class AdminPlanOut(BaseModel):
    """Тариф для админки: с флагами и служебными полями."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    title: str
    description: str
    days: int
    price_rub: int
    price_stars: Optional[int] = None
    # Цена криптой в центах USDT (150 = 1.50 USDT); None — оплата криптой выключена
    price_usdt_cents: Optional[int] = None
    is_active: bool
    sort_order: int
    badge: Optional[str] = None


class AdminPlansOut(BaseModel):
    plans: List[AdminPlanOut]
    promos: List[PromoOut]
    # Продажи: paid — сколько оплат, amount_rub — сумма
    sales: Dict[str, int] = {}


class WalletStarsOut(BaseModel):
    """Баланс звёзд бота в Telegram (`getMyStarBalance`)."""

    configured: bool = False
    amount: int = 0
    error: Optional[str] = None


class WalletCryptoOut(BaseModel):
    """Баланс приложения в Crypto Pay (`getBalance`) по монетам."""

    configured: bool = False
    asset: str = "USDT"
    balances: List[Dict[str, str]] = []
    error: Optional[str] = None


class WalletJournalOut(BaseModel):
    """Журнал оплат — для сверки с балансами кошельков."""

    paid_count: int = 0
    paid_rub: int = 0
    pending_count: int = 0
    # Сколько оплаченных записей по каждому провайдеру (stars / crypto / manual)
    by_provider: Dict[str, int] = {}


class WalletsOut(BaseModel):
    """Кошельки в админке: звёзды бота, крипта Crypto Pay и журнал оплат."""

    stars: WalletStarsOut
    crypto: WalletCryptoOut
    journal: WalletJournalOut


class PlanIn(BaseModel):
    """Правка тарифа из админки: меняем только то, что передали."""

    title: Optional[str] = None
    description: Optional[str] = None
    days: Optional[int] = None
    price_rub: Optional[int] = None
    price_stars: Optional[int] = None
    # Цена криптой в центах USDT: 0 или None очищает (тариф недоступен для крипты)
    price_usdt_cents: Optional[int] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    badge: Optional[str] = None


class PromoIn(BaseModel):
    """Акция из админки: название, описание, процент, срок, лимит и тарифы."""

    title: Optional[str] = None
    description: Optional[str] = None
    percent: Optional[int] = None
    is_active: Optional[bool] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    max_paid: Optional[int] = None
    applies_to: Optional[List[str]] = None


class PaymentOut(BaseModel):
    """Строка журнала платежей."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    paid_at: Optional[datetime] = None
    user_id: Optional[int] = None
    plan_code: str
    amount_rub: int
    discount_percent: int
    provider: str
    external_id: Optional[str] = None
    status: str
    days: int
    premium_until: Optional[datetime] = None
    note: Optional[str] = None


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
    # Курсорная пагинация «лент» (новинки): `next_cursor` — позиция последней
    # карточки. Пока ленту листают, парсер добавляет файлы сверху; с курсором
    # выдача не сдвигается, поэтому догрузка всегда идёт вниз и ничего не теряется.
    next_cursor: Optional[str] = None
    has_more: bool = False


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
    media_today: int = 0          # из них добавлено за текущие отчётные сутки (МСК)
    # Когда в тред последний раз добавился видимый файл (на карточке треда
    # показываем именно это время — видно, когда тред обновлялся)
    last_media_at: Optional[datetime] = None

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


class ThreadDetailOut(BaseModel):
    """Публичная страница треда: метаданные и счётчики файлов.

    Файлы отдаются отдельным запросом (`/boards/{slug}/media?thread=…`) — так
    страница треда переиспользует ту же ленту с догрузкой, что и раздел.
    """

    thread_id: int
    board_id: int
    board_slug: str
    board_title: Optional[str] = None
    subject: Optional[str] = None
    comment: Optional[str] = None
    posts_count: int = 0
    files_count: int = 0
    views_count: int = 0
    media_total: int = 0            # видимых файлов в архиве
    thread_timestamp: Optional[datetime] = None
    last_media_at: Optional[datetime] = None
    is_premium: bool = False        # премиум-тред или премиум-раздел
    locked: bool = False            # подписки у зрителя нет — полный контент закрыт


class ThreadRefOut(BaseModel):
    """Краткая ссылка на тред: для карты сайта и перелинковки."""

    thread_id: int
    board_slug: str
    subject: Optional[str] = None
    media_total: int = 0
    last_media_at: Optional[datetime] = None


class ThreadRefListOut(BaseModel):
    items: List[ThreadRefOut]
    page: int
    per_page: int
    total: int


class MagicIssueIn(BaseModel):
    """Запрос от Telegram-бота: для кого выпустить ссылку входа."""

    telegram_id: int = Field(gt=0)
    username: Optional[str] = Field(None, max_length=64)


class MagicLinkOut(BaseModel):
    """Одноразовая ссылка входа: отдаётся боту или админке."""

    url: str
    expires_at: datetime
    telegram_id: Optional[int] = None
    user_id: int


class TelegramStatusOut(BaseModel):
    """Статус подписки для бота: что показать по `/status`."""

    user_id: int
    telegram_id: int
    is_active: bool = True
    premium_active: bool = False
    premium_until: Optional[datetime] = None
    marks_count: int = 0


class MagicConsumeOut(BaseModel):
    """Результат входа по ссылке (cookie сессии ставится в ответе)."""

    ok: bool
    redirect: str = "/"


class SitemapMediaOut(BaseModel):
    """Файл в карте сайта: только то, что нужно роботу (адрес строится по id)."""

    id: int
    created_at: Optional[datetime] = None
    media_type: str = "image"
    locked: bool = False        # премиум-файл без подписки: превью не отдаём


class SitemapMediaListOut(BaseModel):
    items: List[SitemapMediaOut]
    page: int
    per_page: int
    total: int


class SitemapVideoOut(BaseModel):
    """Видео для карты с `<video:video>`: нужны длительность и размер."""

    id: int
    created_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    file_size: Optional[int] = None


class SitemapVideoListOut(BaseModel):
    items: List[SitemapVideoOut]
    page: int
    per_page: int
    total: int


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


class ResumePointIn(BaseModel):
    """Точка возврата от клиента: тред + последний просмотренный файл."""

    thread_id: int = Field(gt=0)
    media_id: int = Field(gt=0)
    # Позиция файла в списке треда (0-based) и полный размер треда на момент просмотра
    index: int = Field(ge=0, default=0)
    total: int = Field(ge=0, default=0)


class ResumePointOut(BaseModel):
    """Сохранённая точка возврата (поле `index` — как в localStorage-формате фронта)."""

    thread_id: int
    media_id: int
    index: int
    total: int
    updated_at: datetime


class ResumeListOut(BaseModel):
    """Все точки возврата пользователя — свежие сверху."""

    items: List[ResumePointOut] = []
