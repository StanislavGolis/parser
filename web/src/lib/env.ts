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

/**
 * Публичный адрес сайта (canonical, sitemap, robots, Open Graph).
 * Задаётся переменной SITE_URL у сервиса web; по умолчанию — прод-домен.
 */
export const SITE_URL = (process.env.SITE_URL ?? "https://dredg.ru").replace(/\/+$/, "");

/** Разрешает URL медиа из API (относительный /api/... → адрес клиентского API). */
export function mediaUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  if (/^https?:\/\//i.test(url)) return url;
  return apiPathForClient(url);
}

/**
 * Абсолютный URL к файлу сайта — для Open Graph и schema.org (JSON-LD).
 * Внешние ссылки возвращаем как есть.
 */
export function absoluteUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  if (/^https?:\/\//i.test(url)) return url;
  return `${SITE_URL}${url.startsWith("/") ? url : `/${url}`}`;
}

export function apiPathForClient(path: string): string {
  return joinApi(PUBLIC_API_BASE, path);
}
