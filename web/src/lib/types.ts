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

/** Доска в админ-панели. */
export interface AdminBoard extends Board {
  parse_enabled: boolean;
  is_visible: boolean;
  has_access_code: boolean;
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
  /** Подписанный URL на файл в B2 (может отсутствовать, если B2 не настроен). */
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

export interface DownloadResult {
  media_id: number;
  counted: boolean;
  url: string;
}

/** Индекс доски по id — чтобы показывать slug/title на плитках лент. */
export type BoardsById = Record<number, Board>;
