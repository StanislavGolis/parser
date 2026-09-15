export type MediaType = "image" | "video";
export type SortKey = "new" | "popular";
export type PeriodKey = "day" | "week" | "month";

export interface Board {
  id: number;
  slug: string;
  title: string;
  description: string | null;
  media_count: number;
  /** Сколько файлов прибавилось за текущие отчётные сутки (МСК): «+N за сегодня». */
  media_today?: number;
  /** Премиум-раздел: превью размыты, полный контент — по подписке. */
  is_premium: boolean;
  /** Премиум, но подписки у зрителя нет (контент закрыт). */
  locked?: boolean;
  /** До 4 свежих превью раздела — мозаика 2×2 на карточке каталога. */
  cover_thumbs?: string[];
}

/** Доска в админ-панели (с живой статистикой). */
export interface AdminBoard extends Board {
  /** Источник раздела: по нему админка раскладывает доски по вкладкам источников. */
  source_id?: number | null;
  /** Ручные превью карточки раздела: id файлов в порядке плиток (пусто — авто). */
  cover_media_ids?: number[];
  parse_enabled: boolean;
  is_visible: boolean;
  sort_order: number;
  /** Режим выбора тредов: all — все, selected — только включённые вручную. */
  parse_mode: "all" | "selected";
  media_total: number;
  media_downloaded: number;
  media_in_s3: number;
  media_missing: number;
  threads_active: number;
  threads_parsing: number;
  /** Треды в очереди на докачку. */
  threads_pending: number;
  /** Треды, выпавшие из каталога форума. */
  threads_dead: number;
  files_in_catalog: number;
  threads_posts_total: number;
  threads_views_total: number;
  last_scan: string | null;
  views_total: number;
  downloads_total: number;
  /** Каталог раздела недоступен (2ch вернул 500/404 — раздел удалён). */
  catalog_error?: string | null;
}

/** ── Админка: реестр источников и журнал прогонов ─────────────────── */

/** Состояние прогона источника (ключи `parser:{code}:*` в Redis). */
export interface SourceStatus {
  code: string;
  /** Источник запущен кнопкой «Запустить» в админке. */
  enabled: boolean;
  /** Контейнер источника жив (heartbeat). */
  up: boolean;
  /** Идёт работа прямо сейчас. */
  alive: boolean;
  /** Текущий раздел (доска) прогона. */
  current: string | null;
  /** Прогресс текущего прохода (phase, thread_id, files_done/files_total). */
  progress: ParserProgress | null;
}

/** Один прогон источника (таблица `parse_runs`). */
export interface ParseRun {
  id: number;
  started_at: string | null;
  finished_at: string | null;
  status: string; // running | ok | error | stopped
  phase: string | null;
  stats: Record<string, unknown>;
  error: string | null;
}

/** Источник контента в реестре (вкладка «Источники», вкладки в «Контенте»). */
export interface SourceInfo {
  id: number;
  code: string;
  title: string;
  kind: string; // json | html — какой адаптер обслуживает источник
  base_url: string;
  is_enabled: boolean;
  schedule_minutes: number;
  rate_limit_rps: number;
  budget_minutes: number;
  sort_order: number;
  config: Record<string, unknown>;
  boards_total: number;
  media_total: number;
  status: SourceStatus;
  runs: ParseRun[];
}

export interface SystemTotals {
  boards_total: number;
  boards_parsed: number;
  media_total: number;
  media_in_s3: number;
  media_downloaded: number;
  media_missing: number;
  threads_active: number;
  threads_parsing: number;
  threads_pending: number;
  threads_dead: number;
  files_in_catalog: number;
  threads_posts_total: number;
  threads_views_total: number;
  views_total: number;
  downloads_total: number;
}

export interface AdminOverview {
  generated_at: string;
  totals: SystemTotals;
  boards: AdminBoard[];
  parser_up: boolean;
  parser_enabled: boolean;
  parser_alive: boolean;
  parser_current_board: string | null;
}

/** Раздел источника (аналог «доски форума») в сопоставлении с нашей БД.
 *
 * Так админка показывает, что вообще предлагает источник: 2ch — доски из
 * `index.json`, сайт — свои категории. Отсюда администратор выбирает разделы.
 */
export interface SourceBoard {
  slug: string;
  name: string | null;
  /** Рубрика источника: категория доски на 2ch, «категория сайта» у сайтов. */
  group: string | null;
  /** Сколько «тредов» источник показывает в разделе (оценка). */
  hint: number;
  in_db: boolean;
  parse_enabled: boolean;
  parse_mode: string | null;
  is_visible: boolean;
  is_premium: boolean;
  media_total: number;
  media_in_s3: number;
  threads_active: number;
}

/** Тред доски со статистикой файлов и превью. */
export interface BoardThread {
  board_id: number;
  thread_id: number;
  subject: string | null;
  comment: string | null;
  posts_count: number;
  files_count: number;
  files_detected: number;
  views_count: number;
  thread_timestamp: string | null;
  last_scanned_at: string | null;
  is_active: boolean;
  /** Гигиена обхода (админка). */
  misses: number;
  missing_since: string | null;
  /** «Парсить» включён, но тред давно не сканировался. */
  is_stale: boolean;
  /** Очередь докачки (двухфазный цикл): причина и время попытки. */
  pending_scan: boolean;
  pending_reason: string | null;
  last_scan_attempt_at: string | null;
  /** Итог последнего прохода: до какого поста обработано и сводка. */
  last_post_num: number | null;
  last_scan_errors: number;
  last_scan_note: string | null;
  /** Управление из админки. */
  parse_enabled: boolean;
  is_visible: boolean;
  is_premium: boolean;
  /** Премиум-тред (с учётом доски), но подписки у зрителя нет. */
  locked?: boolean;
  media_total: number;
  media_downloaded: number;
  media_in_s3: number;
  media_missing: number;
  media_visible: number;
  /** Из них добавлено за текущие отчётные сутки (МСК) — «+N за сутки» на карточке. */
  media_today?: number;
  /** Когда в тред последний раз добавился видимый файл (на карточке — вместо даты треда). */
  last_media_at?: string | null;
  preview: MediaItem[];
}

/** Итог удаления тредов вместе с файлами (админка). */
export interface ThreadDeleteResult {
  deleted_threads: number;
  deleted_media: number;
  deleted_objects: number;
  /** Объекты, которые оставили: на них ссылаются файлы других тредов. */
  kept_objects: number;
  /** true — это только прикидка, ничего не удалено. */
  dry_run?: boolean;
}

export interface ThreadList {
  items: BoardThread[];
  page: number;
  per_page: number;
  total: number;
  /** Суммы по доске (описание страницы сканирования). */
  posts_total?: number;
  views_total?: number;
  files_detected_total?: number;
  files_downloaded_total?: number;
  /** Счётчики по состояниям тредов (для чипов фильтра). */
  counts?: Record<string, number> | null;
}

export interface MediaItem {
  id: number;
  board_id: number;
  thread_id: number;
  original_name: string;
  file_size: number;
  mime_type: string;
  media_type: MediaType;
  width: number | null;
  height: number | null;
  views_count: number;
  downloads_count: number;
  popularity_score: number;
  created_at: string;
  source_md5?: string | null;
  file_hash?: string | null;
  /** Оригинал файла (может отсутствовать, если S3 не настроен). */
  url: string | null;
  /** Превью-дериватив (thumb) и оптимизированная версия (web). */
  thumb_url?: string | null;
  web_url?: string | null;
  /** Размытый плейсхолдер (blur-up): показывается, пока грузится превью. */
  blur_url?: string | null;
  /** Длительность видео в секундах (для бейджа). */
  duration_seconds?: number | null;
  /** Премиум-контент: locked — нужна подписка (превью размыто, полный недоступен). */
  is_premium?: boolean;
  locked?: boolean;
  /** Закладка (аналог лайка): публичный счётчик и личный список. */
  marks_count?: number;
  marked?: boolean;
}

export interface MediaList {
  items: MediaItem[];
  page: number;
  per_page: number;
  total: number;
  /**
   * Позиция последней карточки для догрузки «лент» (новинки). Пока ленту листают,
   * парсер добавляет файлы сверху: с курсором выдача не сдвигается, поэтому
   * догрузка всегда идёт вниз и ничего не теряется.
   */
  next_cursor?: string | null;
  has_more?: boolean;
}

export interface MediaDetail extends MediaItem {
  board_slug?: string | null;
  duplicate_of_id?: number | null;
}

export interface ViewResult {
  media_id: number;
  counted: boolean;
}

/** Прогресс бэкфилла деривативов («Оптимизировать медиа»). */
export interface BackfillStatus {
  status: "idle" | "running" | "done" | "error";
  /** Всего файлов в очереди на момент запуска. */
  total: number;
  /** Сколько уже прошли в этом прогоне. */
  done: number;
  /** Сколько ещё осталось в очереди (не поддавшиеся файлы остаются тут). */
  remaining?: number;
  processed?: number;
  errors?: number;
  /** Размер пачки между записями прогресса. */
  batch_size?: number;
  error?: string;
}

/** Прогресс сканирования каталога доски (кнопка «Сканировать треды»). */
export interface ScanStatus {
  status: "idle" | "running" | "done" | "error";
  phase?: "catalog" | "files";
  total: number;
  done: number;
  created?: number;
  updated?: number;
  files_total?: number;
  error?: string;
}

export interface DownloadResult {
  media_id: number;
  counted: boolean;
  url: string;
}

/** Прогресс парсера по текущему треду (для прогресс-бара). */
export interface ParserProgress {
  board_slug?: string;
  phase?: "catalog" | "files";
  thread_id?: number | null;
  files_total?: number;
  files_done?: number;
  updated_at?: string | null;
}

/** Лёгкий статус парсера (частый опрос). */
export interface ParserStatus {
  up: boolean;
  enabled: boolean;
  alive: boolean;
  current_board: string | null;
  progress: ParserProgress | null;
  stall_seconds: number | null;
}

/** Пользователь (доступ к оригиналам и премиум-контенту). */
export interface UserOut {
  id: number;
  email: string;
  /** Срок действия премиума (ISO), null — премиум никогда не активировался. */
  premium_until: string | null;
  /** Премиум активен прямо сейчас. */
  is_premium: boolean;
  /** Сколько меток поставил пользователь («мои метки»). */
  marks_count?: number;
  /** Дата регистрации (ISO) — «с нами с …» в профиле. */
  created_at?: string | null;
}

/** Обращение обратной связи (форма `/feedback`). */
export interface FeedbackItem {
  id: number;
  created_at: string;
  topic: string;
  topic_label: string | null;
  message: string;
  email: string | null;
  page_url: string | null;
  user_id: number | null;
  status: string; // new | in_progress | answered | closed
  admin_note: string | null;
  answered_at: string | null;
}

export interface FeedbackList {
  items: FeedbackItem[];
  total: number;
  counts: Record<string, number>;
}

/** Жалоба на файл (кнопка «Пожаловаться», очередь `/admin/reports`). */
export interface MediaReportItem {
  id: number;
  created_at: string;
  media_id: number;
  user_id: number | null;
  reason: string; // csam | copyright | illegal | spam | other
  reason_label: string | null;
  comment: string | null;
  status: string; // open | hidden | thread_hidden | removed | rejected
  resolved_at: string | null;
  resolution_note: string | null;
  // Контекст файла, на который пожаловались
  media_name: string | null;
  board_slug: string | null;
  thread_id: number | null;
  media_type: string | null;
  thumb_url: string | null;
  media_visible: boolean | null;
  reporter: string | null;
}

export interface MediaReportList {
  items: MediaReportItem[];
  total: number;
  counts: Record<string, number>;
}

/** Хеш в блок-листе запрещённого контента (`blocked_hashes`). */
export interface BlockedHashItem {
  id: number;
  sha256: string;
  reason: string; // csam | copyright | other
  note: string | null;
  created_at: string;
  created_by: string | null;
  media_count: number;
}

/** Результат переключения метки («отличный контент»). */
export interface MarkResult {
  media_id: number;
  marked: boolean;
  marks_count: number;
}

/** Индекс доски по id — чтобы показывать slug/title на плитках лент. */
export type BoardsById = Record<number, Board>;

/** Публичная сводка архива для главной (см. `GET /api/v1/status`). */
export interface SiteStatus {
  files_total: number;
  /** Прирост файлов за текущие отчётные сутки (МСК, 00:00–24:00). */
  files_today: number;
  threads_active: number;
  boards_visible: number;
  /** Границы отчётного периода (UTC, ISO) и подпись для интерфейса. */
  period_start?: string | null;
  period_end?: string | null;
  period_label?: string;
}

/** Пост в Telegram-канале (журнал менеджера канала). */
export interface TelegramPostItem {
  id: number;
  created_at: string;
  published_at: string | null;
  kind: string; // teaser | digest | announce
  caption: string;
  media_ids: number[] | null;
  image_mode: string; // mosaic | single | none
  status: string; // draft | scheduled | published | failed | deleted | cancelled | rejected
  channel: string | null;
  message_id: number | null;
  error: string | null;
  created_by: string | null;
  link: string | null;
  scheduled_at: string | null;
}

export interface TelegramPostList {
  items: TelegramPostItem[];
  total: number;
  counts: Record<string, number>;
}

/** Файл-кандидат для тизера (галерея выбора). */
export interface TelegramCandidate {
  id: number;
  media_type: string;
  thumb_url: string | null;
  board_slug: string | null;
}

/** Предпросмотр поста: текст и готовая картинка (data URL). */
export interface TelegramPreview {
  caption: string;
  image_data_url: string | null;
  chat: string | null;
  configured: boolean;
  warning: string | null;
}

/** Настройки публикации в канал (задан ли токен и канал). */
export interface TelegramStatus {
  configured: boolean;
  channel: string | null;
  bot: string | null;
  chat: string | null;
  kinds: string[];
  image_modes: string[];
  default_blur: number;
}


/** Публичная страница треда `/t/{id}`: метаданные и счётчики файлов. */
export interface ThreadDetail {
  thread_id: number;
  board_id: number;
  board_slug: string;
  board_title: string | null;
  subject: string | null;
  comment: string | null;
  posts_count: number;
  files_count: number;
  views_count: number;
  /** Видимых файлов в архиве (галерея грузится отдельным запросом). */
  media_total: number;
  thread_timestamp: string | null;
  /** Когда в тред добавился последний файл (для lastmod в карте сайта). */
  last_media_at: string | null;
  /** Премиум-тред или премиум-раздел. */
  is_premium: boolean;
  /** Подписки у зрителя нет — полный контент закрыт. */
  locked: boolean;
}

/** Краткая ссылка на тред: карта сайта и блоки перелинковки. */
export interface ThreadRef {
  thread_id: number;
  board_slug: string;
  subject: string | null;
  media_total: number;
  last_media_at: string | null;
}

/** Файл в карте сайта (минимум полей — так карта генерируется быстро). */
export interface SitemapMedia {
  id: number;
  created_at: string | null;
  media_type: string;
  /** Премиум-файл без подписки: превью в карту не отдаём. */
  locked: boolean;
}

export interface SitemapMediaList {
  items: SitemapMedia[];
  page: number;
  per_page: number;
  total: number;
}

/** Видео для карты с `<video:video>`. */
export interface SitemapVideo {
  id: number;
  created_at: string | null;
  duration_seconds: number | null;
  file_size: number | null;
}

export interface SitemapVideoList {
  items: SitemapVideo[];
  page: number;
  per_page: number;
  total: number;
}

export interface ThreadRefList {
  items: ThreadRef[];
  page: number;
  per_page: number;
  total: number;
}

/** Прогресс прогрева дискового кэша медиа. */
export interface MediaCacheWarm {
  status: "idle" | "running" | "done" | "interrupted" | string;
  done: number;
  total: number;
  failed: number;
}

/** Состояние локального кэша медиа (диск сервера) вместе с прогрессом прогрева. */
export interface MediaCacheStats {
  enabled: boolean;
  dir: string;
  files: number;
  bytes: number;
  max_bytes: number;
  min_free_bytes: number;
  used_percent: number;
  disk_total: number;
  disk_free: number;
  hits: number;
  misses: number;
  stored: number;
  evicted_files: number;
  evicted_bytes: number;
  warm: MediaCacheWarm;
}


/** ── Админка: статистика посещаемости ─────────────────────────────── */

export interface StatsTotals {
  visitors: number;
  visits: number;
  pageviews: number;
  events: number;
  registered: number;
}

export interface StatsOverview extends StatsTotals {
  days: number;
  generated_at: string;
  previous: StatsTotals;
  delta: { visitors: number | null; visits: number | null; pageviews: number | null };
  new_visitors: number;
  returning_visitors: number;
  pages_per_visit: number;
}

export interface StatsPoint {
  t: string;
  visitors: number;
  visits: number;
  pageviews: number;
}

export interface StatsTimeseries {
  group: "day" | "hour";
  days: number;
  points: StatsPoint[];
}

export interface StatsPages {
  days: number;
  items: Array<{ path: string; views: number; visitors: number }>;
}

export interface StatsSources {
  days: number;
  referrers: Array<{ host: string; visits: number; visitors: number }>;
  utm: Array<{ source: string; visits: number }>;
}

export interface StatsNameCount {
  name: string;
  hits: number;
  visitors: number;
}

export interface StatsDevices {
  days: number;
  devices: StatsNameCount[];
  browsers: StatsNameCount[];
  os: StatsNameCount[];
}

export interface StatsEvents {
  days: number;
  items: Array<{ event: string; hits: number; visitors: number }>;
}

export interface StatsContentMedia {
  id: number;
  name: string;
  board: string;
  count: number;
}

export interface TelegramDigest {
  media_ids: number[];
  boards: string[];
  caption: string;
  period: string;
}

export interface TelegramAutopost {
  enabled: boolean;
  posts_per_day: number;
  quiet_from: number;
  quiet_to: number;
  require_approval: boolean;
  boards: string[] | null;
  period: string;
  blur: number;
  last_check_at: string | null;
  last_post_at: string | null;
  published_last_day: number;
  allowed: boolean;
  reason: string | null;
}

export interface GiveawayItem {
  id: number;
  created_at: string;
  title: string;
  kind: string;
  prize_days: number;
  starts_at: string;
  ends_at: string;
  status: string;
  winners: Array<Record<string, string | number>> | null;
  entries: number;
  link: string | null;
}

export interface StatsContent {
  days: number;
  views: StatsContentMedia[];
  downloads: StatsContentMedia[];
  marks: StatsContentMedia[];
  boards: Array<{ board: string; views: number }>;
}

export interface StatsHealth {
  days: number;
  statuses: string[];
  items: Array<{ date: string; counters: Record<string, number>; total: number }>;
}

/** ── Админка: пользователи ────────────────────────────────────────── */

export interface AdminUser {
  id: number;
  email: string | null;
  /** Готовое имя аккаунта: email, @ник или Telegram ID (у бот-аккаунтов email пуст). */
  display_name: string;
  telegram_id: number | null;
  telegram_username: string | null;
  is_active: boolean;
  is_admin: boolean;
  created_at: string | null;
  premium_until: string | null;
  premium_active: boolean;
  marks_count: number;
  views_count: number;
  downloads_count: number;
  last_seen_at: string | null;
  sessions_active: number;
}

export interface AdminUserList {
  items: AdminUser[];
  page: number;
  per_page: number;
  total: number;
}

export interface AdminUserSession {
  id: number;
  created_at: string | null;
  last_seen_at: string | null;
  expires_at: string | null;
  ip_hash: string | null;
  user_agent: string | null;
  active: boolean;
}

export interface AdminUserCard extends AdminUser {
  sessions: AdminUserSession[];
  marks: Array<{ at: string | null; media_id: number; name: string; board: string }>;
  downloads: Array<{ at: string | null; media_id: number; name: string }>;
  audit: Array<{ at: string | null; actor: string | null; action: string; details: string | null }>;
}

export interface AdminAuditItem {
  at: string | null;
  actor: string | null;
  action: string;
  target: string | null;
  details: string | null;
}

export interface AdminAuditList {
  items: AdminAuditItem[];
}

/** Тариф для админки: цена и срок правятся без деплоя. */
export interface AdminPlan {
  code: string;
  title: string;
  description: string;
  days: number;
  price_rub: number;
  /** Цена в звёздах Telegram (задаётся вручную); null — оплата звёздами выключена. */
  price_stars: number | null;
  is_active: boolean;
  sort_order: number;
  badge: string | null;
}

/** Акция: своё название, описание, процент и условия; включается вручную. */
export interface PromoItem {
  id: number;
  title: string;
  description: string;
  percent: number;
  is_active: boolean;
  active: boolean;
  reason: string;
  starts_at: string | null;
  ends_at: string | null;
  days_left: number | null;
  max_paid: number | null;
  paid_left: number | null;
  /** Пустой список — акция на все тарифы. */
  applies_to: string[];
}

export interface AdminPlans {
  plans: AdminPlan[];
  promos: PromoItem[];
  sales: Record<string, number>;
}

/** Строка журнала оплат. */
export interface PaymentItem {
  id: number;
  created_at: string;
  paid_at: string | null;
  user_id: number | null;
  plan_code: string;
  amount_rub: number;
  discount_percent: number;
  provider: string;
  external_id: string | null;
  status: string;
  days: number;
  premium_until: string | null;
  note: string | null;
}

/** Витрина тарифов (то же, что видит бот и сайт). */
export interface PlanPrice {
  code: string;
  title: string;
  description: string;
  days: number;
  price_rub: number;
  price_now: number;
  price_stars: number | null;
  stars_now: number | null;
  discount_percent: number;
  promo_id: number | null;
  promo_title: string | null;
  promo_description: string | null;
  badge: string | null;
  is_forever: boolean;
}

export interface PlansView {
  plans: PlanPrice[];
  promos: PromoItem[];
}
