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

/**
 * Режим сайта (модель Dredger 2.0):
 * - `public` — текущее поведение: контент открыт, SEO включён;
 * - `closed` — сайт закрыт: анонимные запросы уходят на `/login`, поисковикам всё
 *   запрещено (`X-Robots-Tag: noindex`, `robots: Disallow: /`, карты → 404),
 *   age gate и онбординг не показываются.
 *
 * Режим, а не удаление кода: публичную зону (`safe.dredg.ru`) можно поднять на тех
 * же компонентах, просто вернув `SITE_MODE=public`.
 */
export const SITE_MODE = (process.env.SITE_MODE ?? "public").trim().toLowerCase();
export const SITE_CLOSED = SITE_MODE === "closed";

/** Ник Telegram-бота (без @) — для кнопки «Войти через Telegram» на входе. */
export const TELEGRAM_BOT_USERNAME = (process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME ?? "")
  .trim()
  .replace(/^@/, "");

/** Пути, доступные без входа в закрытом режиме (проверяем по префиксу).
 *  Правовые страницы открыты: правообладатель и проверяющий должны прочитать
 *  правила и контакты без регистрации. */
export const PUBLIC_PATHS = [
  "/login",
  "/auth",
  "/healthz",
  "/robots.txt",
  "/favicon.ico",
  "/tos",
  "/dmca",
  "/privacy",
];

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
