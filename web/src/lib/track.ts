"use client";

/**
 * Своя аналитика: анонимный идентификатор посетителя/визита и отправка хитов
 * на наш API (`POST /api/v1/hit`). Никаких внешних счётчиков и рекламных пикселей.
 */

const SID_COOKIE = "dv_sid";
const VISIT_COOKIE = "dv_visit";
/** Источник захода, который запомнил middleware (см. `web/src/middleware.ts`). */
const SOURCE_REF_COOKIE = "dv_ref";
const SOURCE_UTM_COOKIE = "dv_utm";
const SID_MAX_AGE = 60 * 60 * 24 * 30; // 30 дней — «посетитель»
const VISIT_GAP_MS = 30 * 60 * 1000; // пауза, после которой визит считается новым

function readCookie(name: string): string {
  if (typeof document === "undefined") return "";
  const prefix = `${name}=`;
  const found = document.cookie.split("; ").find((c) => c.startsWith(prefix));
  return found ? found.slice(prefix.length) : "";
}

function writeCookie(name: string, value: string, maxAgeSeconds: number): void {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=${value}; path=/; max-age=${maxAgeSeconds}; samesite=lax`;
}

/** Анонимный id посетителя (без привязки к аккаунту, просто случайная строка). */
function sessionId(): string {
  let sid = readCookie(SID_COOKIE);
  if (!/^[A-Za-z0-9_-]{8,40}$/.test(sid)) {
    const raw =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now()}${Math.random()}`;
    sid = raw.replace(/[^A-Za-z0-9]/g, "").slice(0, 32);
    writeCookie(SID_COOKIE, sid, SID_MAX_AGE);
  }
  return sid;
}

/** Внешний `document.referrer`: свой домен и пустое значение не считаем источником. */
function externalReferrer(): string | undefined {
  if (typeof document === "undefined" || typeof window === "undefined") return undefined;
  if (!document.referrer) return undefined;
  try {
    const host = new URL(document.referrer).hostname.toLowerCase().replace(/^www\./, "");
    const own = window.location.hostname.toLowerCase().replace(/^www\./, "");
    return host && host !== own ? host : undefined;
  } catch {
    return undefined;
  }
}

/** `utm_source` из адреса страницы (метку ставит внешняя ссылка). */
function urlUtm(): string | undefined {
  if (typeof window === "undefined") return undefined;
  const value = new URLSearchParams(window.location.search).get("utm_source");
  return value ? value.slice(0, 80) : undefined;
}

/**
 * Источник захода из cookie: его пишет middleware при первом заходе.
 *
 * Нужен там, где `document.referrer` не доживает: закрытый режим уводит анонима на
 * `/login` редиректом, а мессенджер открывает ссылку своим браузером.
 */
function sourceFromCookies(): { referrer?: string; utmSource?: string } {
  const ref = readCookie(SOURCE_REF_COOKIE);
  const utm = readCookie(SOURCE_UTM_COOKIE);
  return {
    referrer: /^[a-z0-9.-]{3,120}$/.test(ref) ? ref : undefined,
    utmSource: utm ? utm.slice(0, 80) : undefined,
  };
}

/** Новый ли это визит, и откуда пришли (нужно только на первом хите визита). */
function visitState(): { isNewVisit: boolean; referrer?: string; utmSource?: string } {
  const now = Date.now();
  const last = Number(readCookie(VISIT_COOKIE) || 0);
  const isNewVisit = !last || now - last > VISIT_GAP_MS;
  writeCookie(VISIT_COOKIE, String(now), Math.ceil(VISIT_GAP_MS / 1000));
  const saved = sourceFromCookies();
  return {
    isNewVisit,
    // document.referrer осмысленен только при входе извне: дальше переходы внутренние.
    // Если он потерялся (редирект, мессенджер) — берём источник, сохранённый middleware.
    referrer: isNewVisit ? externalReferrer() ?? saved.referrer : undefined,
    utmSource: isNewVisit ? urlUtm() ?? saved.utmSource : undefined,
  };
}

async function send(body: Record<string, unknown>): Promise<void> {
  if (typeof window === "undefined") return;
  try {
    await fetch("/api/v1/hit", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ session_id: sessionId(), ...body }),
      keepalive: true,
    });
  } catch {
    /* аналитика не должна мешать сайту */
  }
}

/** Отмечает просмотр страницы (адрес с query — так видны фильтры в отчёте). */
export function trackPageView(path?: string): void {
  const state = visitState();
  void send({
    path: path ?? window.location.pathname + window.location.search,
    new_visit: state.isNewVisit,
    referrer: state.referrer,
    utm_source: state.utmSource,
  });
}

/** Отмечает событие интерфейса: lightbox_open, download_click, filter_click, … */
export function trackEvent(event: string, path?: string): void {
  const state = visitState();
  void send({
    path: path ?? window.location.pathname,
    event,
    // визит считаем только по просмотрам страниц: событие не начинает визит
    new_visit: false,
    referrer: state.referrer,
  });
}
