"use client";

/**
 * Своя аналитика: анонимный идентификатор посетителя/визита и отправка хитов
 * на наш API (`POST /api/v1/hit`). Никаких внешних счётчиков и рекламных пикселей.
 */

const SID_COOKIE = "dv_sid";
const VISIT_COOKIE = "dv_visit";
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

/** Новый ли это визит, и реферер (нужен только на первом хите визита). */
function visitState(): { isNewVisit: boolean; referrer?: string } {
  const now = Date.now();
  const last = Number(readCookie(VISIT_COOKIE) || 0);
  const isNewVisit = !last || now - last > VISIT_GAP_MS;
  writeCookie(VISIT_COOKIE, String(now), Math.ceil(VISIT_GAP_MS / 1000));
  return {
    isNewVisit,
    // document.referrer осмысленен только при входе извне: дальше переходы внутренние
    referrer: isNewVisit ? document.referrer || undefined : undefined,
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
    utm_source: new URLSearchParams(window.location.search).get("utm_source") ?? undefined,
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
