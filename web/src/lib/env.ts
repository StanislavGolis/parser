// Адреса API-бэкенда (FastAPI).

/** Базовый URL для запросов из браузера. */
export const PUBLIC_API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/+$/, "");

/**
 * Базовый URL для серверного рендеринга.
 * Внешний адрес недоступен из контейнера, поэтому для SSR используется
 * отдельная переменная (или тот же NEXT_PUBLIC_API_BASE).
 */
export const SERVER_API_BASE = (
  process.env.API_BASE_SERVER ??
  process.env.NEXT_PUBLIC_API_BASE ??
  "http://localhost:8000"
).replace(/\/+$/, "");

/** Склеивает базовый URL и путь API. */
export function joinApi(base: string, path: string): string {
  return `${base}${path}`;
}

export function apiPathForClient(path: string): string {
  return joinApi(PUBLIC_API_BASE, path);
}
