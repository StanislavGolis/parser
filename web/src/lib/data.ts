/**
 * Серверный слой данных (используется только в Server Components).
 * fetch с next.revalidate попадает в Data Cache Next.js, поэтому частота
 * запросов к API ограничена, а страницы остаются живыми (SSR) и не требуют
 * доступного API в момент сборки.
 *
 * ВНИМАНИЕ: файл предназначен только для Server Components; в клиентских
 * компонентах используйте src/lib/api.ts.
 */
import { cookies } from "next/headers";

import { ApiError } from "./api";
import { SERVER_API_BASE } from "./env";
import type {
  Board,
  MediaDetail,
  MediaItem,
  MediaList,
  MediaType,
  PeriodKey,
  SortKey,
  ThreadList,
} from "./types";

const REVALIDATE = {
  boards: 30, // 30 сек: главная быстро отражает приватность/скрытие досок
  feed: 60, // 1 мин
  board: 60, // 1 мин
  top: 120, // 2 мин
  detail: 120, // 2 мин
} as const;

async function serverFetch<T>(path: string, revalidate: number, fallback?: T): Promise<T> {
  let res: Response;
  try {
    // Пробрасываем cookie браузера в SSR-запрос: приватные разделы
    // проверяют доступ по cookie ba_{slug} на стороне API.
    const cookieStore = cookies();
    res = await fetch(`${SERVER_API_BASE}${path}`, {
      next: { revalidate },
      headers: {
        accept: "application/json",
        cookie: cookieStore.toString(),
      },
    });
  } catch {
    if (fallback !== undefined) return fallback;
    throw new ApiError(0, "API недоступен");
  }
  if (!res.ok) {
    if (fallback !== undefined && res.status >= 500) return fallback;
    throw new ApiError(res.status, `API ${res.status}: ${res.statusText}`);
  }
  return (await res.json()) as T;
}

const EMPTY_LIST: MediaList = { items: [], page: 1, per_page: 30, total: 0 };

export async function getBoards(): Promise<Board[]> {
  const data = await serverFetch<Board[]>("/api/v1/boards", REVALIDATE.boards, []);
  return Array.isArray(data) ? data : [];
}

export async function getFeedPage(page: number, perPage: number, type?: MediaType | null): Promise<MediaList> {
  const q = new URLSearchParams({ page: String(page), per_page: String(perPage) });
  if (type) q.set("type", type);
  return serverFetch<MediaList>(`/api/v1/feed?${q}`, REVALIDATE.feed, EMPTY_LIST);
}

export async function getBoardMediaPage(
  slug: string,
  sort: SortKey,
  page: number,
  perPage: number,
  type?: MediaType | null,
  threadId?: number | null,
): Promise<MediaList> {
  const q = new URLSearchParams({ page: String(page), per_page: String(perPage), sort });
  if (type) q.set("type", type);
  if (threadId) q.set("thread", String(threadId));
  const fallback: MediaList = { items: [], page, per_page: perPage, total: 0 };
  return serverFetch<MediaList>(`/api/v1/boards/${encodeURIComponent(slug)}/media?${q}`, REVALIDATE.board, fallback);
}

export async function getBoardThreads(
  slug: string,
  page: number,
  perPage: number,
): Promise<ThreadList> {
  const q = new URLSearchParams({ page: String(page), per_page: String(perPage) });
  const fallback: ThreadList = { items: [], page, per_page: perPage, total: 0 };
  return serverFetch<ThreadList>(`/api/v1/boards/${encodeURIComponent(slug)}/threads?${q}`, REVALIDATE.board, fallback);
}

export async function getSearchPage(
  q: string,
  page: number,
  perPage: number,
  type?: MediaType | null,
): Promise<MediaList> {
  const params = new URLSearchParams({ q, page: String(page), per_page: String(perPage) });
  if (type) params.set("type", type);
  const fallback: MediaList = { items: [], page, per_page: perPage, total: 0 };
  return serverFetch<MediaList>(`/api/v1/search?${params}`, REVALIDATE.board, fallback);
}

export async function getTopMedia(
  period: PeriodKey,
  type?: MediaType | null,
  limit = 60,
): Promise<MediaItem[]> {
  const q = new URLSearchParams({ period, limit: String(limit) });
  if (type) q.set("type", type);
  const fallback: MediaItem[] = [];
  const data = await serverFetch<MediaItem[]>(`/api/v1/top?${q}`, REVALIDATE.top, fallback);
  return Array.isArray(data) ? data : [];
}

export async function getMediaDetail(id: number): Promise<MediaDetail | null> {
  return serverFetch<MediaDetail | null>(`/api/v1/media/${id}`, REVALIDATE.detail, null);
}

/**
 * Избранное текущего пользователя (требует сессии).
 * `revalidate: 0` — персональные данные не кэшируем; при 401 страница
 * показывает приглашение войти (см. `/favorites`).
 */
export async function getFavoritesPage(page: number, perPage: number): Promise<MediaList> {
  const q = new URLSearchParams({ page: String(page), per_page: String(perPage) });
  const fallback: MediaList = { items: [], page, per_page: perPage, total: 0 };
  return serverFetch<MediaList>(`/api/v1/favorites?${q}`, 0, fallback);
}
