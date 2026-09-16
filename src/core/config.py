from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # База данных
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/parser"

    # Redis (кэш, rate limiting, счётчики)
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Хранилище
    STORAGE_PATH: str = "./storage/media"
    
    # Парсинг
    PARSE_INTERVAL: int = 30  # секунд
    BOARDS_TO_PARSE: list[str] = ["b", "pr", "sci"]
    
    # Ограничения
    MAX_FILES_PER_POST: int = 5
    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100 MB
    
    # Задержки для защиты от бана
    REQUEST_DELAY: float = 0.5  # секунд между запросами

    # Коммит БД каждые N файлов внутри треда: файлы становятся видны на сайте
    # по мере скачивания, а сбой теряет максимум N файлов (0 — коммит только
    # после треда, как было раньше).
    DB_COMMIT_EVERY_FILES: int = 25

    # Сверка данных (reconciliation)
    RECONCILE_MINUTES: int = 60  # период сверки БД ↔ хранилище; 0 — только при старте, −1 — не делать (сверку ведёт один контейнер, см. docker-compose.prod.yml)

    # Гигиена обхода тредов (чтобы не было «забытых» тредов)
    DEAD_THREAD_AFTER_MISSES: int = 3  # столько проходов каталога подряд без треда → is_active=False
    STALE_SCAN_HOURS: int = 24         # тред не сканировался дольше → «просрочен» (чип в админке)
    # Бюджет цикла: после N минут фаза B прерывается, а остаток очереди
    # продолжается в следующем цикле (0 — без ограничения, гнать до конца очереди)
    PARSE_CYCLE_BUDGET_MINUTES: int = 30

    # Параллельные загрузки внутри треда: сколько файлов тянуть с форума
    # одновременно (1 — строго последовательно, как раньше). Параллелится только
    # скачивание; валидация, S3 и запись в БД всегда последовательны.
    MAX_PARALLEL_DOWNLOADS: int = 2
    # Ограничение памяти под «предзагрузку» пачки файлов: крупные файлы качаются
    # по одному, чтобы не держать в RAM сотни мегабайт
    PREFETCH_MAX_BYTES: int = 64 * 1024 * 1024
    # Параллельная выгрузка в S3 внутри треда. По умолчанию 1: замер на нашем
    # S3-эндпоинте показал, что одновременные загрузки в 3 раза МЕДЛЕННЕЕ
    # (3.0 МБ/с против 10.9 МБ/с при 8 МБ объектах) — хранилище троттлит
    # соединения. Значение >1 имеет смысл только после замера на своём эндпоинте
    # (комментарий в README §3.1, конвейер: подготовка → S3 → БД).
    MAX_PARALLEL_UPLOADS: int = 1

    # Логировать SQL-запросы (echo у SQLAlchemy). В прод — выключено: парсер
    # печатает каждый запрос, логи растут на гигабайты. Включать только для отладки.
    SQL_ECHO: bool = False
    # Cookie сессии только по HTTPS (в проде за SSL — включить). Локально без
    # сертификата оставить false, иначе браузер не сохранит cookie.
    SESSION_COOKIE_SECURE: bool = False

    # ── Локальный кэш медиа (диск сервера) ────────────────────────
    # S3 у провайдера отдаёт ~3 МБ/с, локальный SSD — 500+ МБ/с. Файлы, прочитанные
    # один раз, остаются на диске: повторные запросы (в т.ч. премиум-оригиналы)
    # обслуживаются локально, трафик чтения из S3 → почти нулю. Кэш — расходник:
    # первоисточник в S3, очищать/терять его безопасно.
    MEDIA_CACHE_ENABLED: bool = True
    MEDIA_CACHE_DIR: str = "/data/cache"
    MEDIA_CACHE_MAX_BYTES: int = 40 * 1024**3      # 40 ГБ (вся библиотека ~8 ГБ)
    MEDIA_CACHE_MIN_FREE_BYTES: int = 10 * 1024**3  # не забивать диск под ноль
    MEDIA_CACHE_WARM_WORKERS: int = 4               # параллельных загрузок при прогреве

    # ── Деривативы видео ──────────────────────────────────────────
    # Перекодировать видео в 720p при обработке файла. Архивный источник это
    # выключает (`VIDEO_WEB_ENABLED=0`): длинные webm из архива занимают десятки
    # минут на файл, а оригинал и так лежит в S3.
    VIDEO_WEB_ENABLED: bool = True

    # ── Вход в админку по email+паролю и восстановление пароля ────
    # Кому разрешён вход в админку и восстановление (через запятую). Для этих
    # адресов автоматически заводятся админ-аккаунты.
    ADMIN_EMAILS: str = ""
    # Срок жизни ссылки восстановления, минуты
    ADMIN_RESET_TTL_MINUTES: int = 30
    # База для ссылок в письмах, например https://example.com (пусто — из запроса)
    PUBLIC_BASE_URL: str = ""
    # Публичный адрес сайта для уведомлений поисковиков (IndexNow): карты сайта и
    # ключ живут на домене web, поэтому указываем тот же адрес, что в SITE_URL web
    SITE_URL: str = ""
    # Ключ IndexNow (32+ символов): файл с ним отдаёт web по /indexnow-key.txt,
    # уведомления о новых страницах отправляет `python -m src.tools.indexnow`
    INDEXNOW_KEY: str = ""
    # Режим сайта (модель Dredger 2.0): `public` — контент открыт, `closed` — сайт
    # закрыт целиком: API отдаёт контент только по действующей сессии, web уводит
    # анонимов на /login, поисковикам запрещена индексация (X-Robots-Tag + robots).
    SITE_MODE: str = "public"

    # ── Telegram (модель Dredger 2.0) ─────────────────────────────
    # Telegram продаёт и выдаёт доступ, сайт показывает. Токен бота нужен шлюзу бота
    # и ручке выдачи magic link; username/channel — для ссылок в интерфейсе.
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_BOT_USERNAME: str = ""   # например dredger_bot (без @)
    TELEGRAM_CHANNEL: str = ""        # например dredger_news (без @)
    # Сколько минут живёт одноразовая ссылка входа
    MAGIC_LINK_TTL_MINUTES: int = 10

    # ── Crypto Pay (CryptoBot): приём крипты ──────────────────────
    # Токен приложения из @CryptoBot → /pay → Create App. Счёт выставляем в `USDT`,
    # суммы берём из `plans.price_usdt` (правятся в админке, без деплоя).
    CRYPTOBOT_TOKEN: str = ""
    CRYPTOBOT_TESTNET: bool = False   # True — отладка на testnet-pay.crypt.bot
    CRYPTOBOT_ASSET: str = "USDT"     # монета счёта (USDT, TON, …)
    # Сколько минут живёт счёт: за это время сумма фиксируется CryptoBot
    CRYPTOBOT_INVOICE_TTL_MINUTES: int = 60

    @property
    def site_closed(self) -> bool:
        """Закрытый режим включён (значение SITE_MODE=closed)."""
        return self.SITE_MODE.strip().lower() == "closed"

    # Пул соединений к БД: под нагрузкой (скан каталогов + прогрева кэша + SSR)
    # дефолтных 5+10 не хватало — API отдавал 500 «QueuePool limit ... timeout»
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 15
    # Переоткрывать соединение раз в 30 минут: защита от «призрачных» сокетов
    DB_POOL_RECYCLE: int = 1800
    # SMTP для писем восстановления. Пусто — почта выключена, останется
    # восстановление через CLI на сервере (см. DEPLOY.md).
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_TLS: str = "ssl"  # ssl | starttls | none

    # ── Ежедневный отчёт на почту (за прошедшие отчётные сутки по МСК) ──
    DAILY_REPORT: bool = True
    # Вариант состава: short — одна строка, standard — цифры и топ разделов,
    # full — плюс ошибки прогонов (см. src/services/daily_report.py)
    DAILY_REPORT_MODE: str = "standard"
    # Кому отправлять. Пусто — админам из ADMIN_EMAILS
    DAILY_REPORT_EMAILS: str = ""
    # Задержка после 00:00 МСК: даём парсеру дописать прогон и статистику
    DAILY_REPORT_DELAY_MINUTES: int = 5

    @property
    def admin_emails(self) -> list[str]:
        """Список админских email'ов (нормализованный, без пустых)."""
        return [e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()]

    # API сайта
    ADMIN_TOKEN: str = ""                     # токен для админ-эндпоинтов
    API_RATE_LIMIT: int = 300                 # JSON-запросов в минуту на IP (ленты, детали, статистика)
    MEDIA_RATE_LIMIT: int = 1500              # запросов медиа-файлов в минуту на IP (превью/оригиналы)
    API_CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8080"
    POPULARITY_RECALC_MINUTES: int = 5        # период пересчёта popularity_score, в минутах

    # ── Своя аналитика посещаемости (вкладка «Статистика») ────────
    ANALYTICS_ENABLED: bool = True            # принимать хиты с сайта (/api/v1/hit)
    ANALYTICS_RETENTION_DAYS: int = 120       # сколько дней хранить сырые посещения
    ANALYTICS_SESSION_MINUTES: int = 30       # пауза, после которой визит считается новым
    ANALYTICS_ERROR_COUNTER_DAYS: int = 14    # срок жизни счётчиков ошибок API в Redis

    # ── Объектное хранилище S3 (Timeweb Cloud) ────────────────────
    # Значения из панели Timeweb: S3 URL, бакет, Access/Secret Key, регион.
    S3_URL: str = "https://s3.twcstorage.ru"
    S3_REGION: str = "ru-1"
    S3_BUCKET: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_ADDRESSING_STYLE: str = "path"  # имя бакета — UUID: используем path-style
    S3_SIGNED_URL_TTL: int = 3600      # срок жизни presigned-URL (резервный режим)

    # Отдача медиа: proxy — через API (бакет не раскрывается клиенту); presigned — прямые ссылки
    MEDIA_DELIVERY: str = "proxy"

    @property
    def storage_endpoint(self) -> str:
        return self.S3_URL or "https://s3.twcstorage.ru"

    @property
    def storage_region(self) -> str:
        return self.S3_REGION or "ru-1"

    @property
    def storage_bucket(self) -> str:
        return self.S3_BUCKET

    @property
    def storage_access_key(self) -> str:
        return self.S3_ACCESS_KEY

    @property
    def storage_secret_key(self) -> str:
        return self.S3_SECRET_KEY
    
    class Config:
        env_file = ".env"
        extra = "ignore"  # не падать из-за «лишних» переменных в .env

settings = Settings()