export type MediaType = "image" | "video";
export type SortKey = "new" | "popular";
export type PeriodKey = "day" | "week" | "month";

export interface Board {
  id: number;
  slug: string;
  title: string;
  description: string | null;
  media_count: number;
  /** Приватный раздел: виден в списке, контент по коду доступа. */
  is_private: boolean;
}

/** Доска в админ-панели (с живой статистикой). */
export interface AdminBoard extends Board {
  parse_enabled: boolean;
  is_visible: boolean;
  has_access_code: boolean;
  sort_order: number;
  /** Режим выбора тредов: all — все, selected — только включённые вручную. */
  parse_mode: "all" | "selected";
  media_total: number;
  media_downloaded: number;
  media_in_s3: number;
  media_missing: number;
  threads_active: number;
  threads_parsing: number;
  files_in_catalog: number;
  threads_posts_total: number;
  threads_views_total: number;
  last_scan: string | null;
  views_total: number;
  downloads_total: number;
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
  is_private: boolean;
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
  /** Управление из админки. */
  parse_enabled: boolean;
  is_visible: boolean;
  is_private: boolean;
  has_access_code: boolean;
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
  /** Подписанный URL на файл в S3 (может отсутствовать, если S3 не настроен). */
  url: string | null;
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

export interface AccessResult {
  granted: boolean;
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

/** Индекс доски по id — чтобы показывать slug/title на плитках лент. */
export type BoardsById = Record<number, Board>;
