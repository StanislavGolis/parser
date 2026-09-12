export type MediaType = "image" | "video";
export type SortKey = "new" | "popular";
export type PeriodKey = "day" | "week" | "month";

export interface Board {
  id: number;
  slug: string;
  title: string;
  description: string | null;
  media_count: number;
  /** Премиум-раздел: превью размыты, полный контент — по подписке. */
  is_premium: boolean;
  /** Премиум, но подписки у зрителя нет (контент закрыт). */
  locked?: boolean;
}

/** Доска в админ-панели (с живой статистикой). */
export interface AdminBoard extends Board {
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

/** Итоговые цифры системы (в админке). */
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

/** Доска форума (список из index.json двача) в сопоставлении с нашей БД. */
export interface ForumBoard {
  slug: string;
  name: string | null;
  category: string | null;
  threads_on_forum: number;
  in_db: boolean;
  parse_enabled: boolean;
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
  preview: MediaItem[];
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
  /** Длительность видео в секундах (для бейджа). */
  duration_seconds?: number | null;
  /** Премиум-контент: locked — нужна подписка (превью размыто, полный недоступен). */
  is_premium?: boolean;
  locked?: boolean;
  /** Метка «отличный контент» (аналог лайка): публичный счётчик и личный список. */
  marks_count?: number;
  marked?: boolean;
}

export interface MediaList {
  items: MediaItem[];
  page: number;
  per_page: number;
  total: number;
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
}

/** Результат переключения метки («отличный контент»). */
export interface MarkResult {
  media_id: number;
  marked: boolean;
  marks_count: number;
}

/** Индекс доски по id — чтобы показывать slug/title на плитках лент. */
export type BoardsById = Record<number, Board>;
