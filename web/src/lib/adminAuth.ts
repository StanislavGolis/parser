"use client";

import { useCallback, useEffect, useState } from "react";

/** Ключ admin-токена в sessionStorage: живёт до закрытия вкладки браузера. */
export const ADMIN_TOKEN_KEY = "admin_token";

/** Email админа: нужен для журнала действий (`X-Admin-Actor`). */
export const ADMIN_EMAIL_KEY = "admin_email";

/** Событие «токен изменился» — синхронизирует гейт в layout и страницы админки. */
const TOKEN_EVENT = "dredge:admin-token";

export function readAdminToken(): string {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(ADMIN_TOKEN_KEY) ?? "";
}

export function writeAdminToken(token: string): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
  window.dispatchEvent(new Event(TOKEN_EVENT));
}

export function clearAdminToken(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(ADMIN_TOKEN_KEY);
  window.sessionStorage.removeItem(ADMIN_EMAIL_KEY);
  window.dispatchEvent(new Event(TOKEN_EVENT));
}

/** Email, под которым вошёл админ (для аудита); пусто — вход по токену. */
export function readAdminEmail(): string {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(ADMIN_EMAIL_KEY) ?? "";
}

export function writeAdminEmail(email: string): void {
  if (typeof window === "undefined") return;
  if (email) window.sessionStorage.setItem(ADMIN_EMAIL_KEY, email);
  else window.sessionStorage.removeItem(ADMIN_EMAIL_KEY);
}

/**
 * Токен админки с подпиской на изменения.
 *
 * Значение читаем в эффекте: на серверном рендере sessionStorage недоступен,
 * поэтому до гидратации возвращаем пустую строку (гейт показывает скелетон,
 * а не форму входа — иначе при живом токене мигала бы форма).
 * `logout()` чистит токен, и все страницы админки сразу возвращаются к входу.
 */
export function useAdminToken(): {
  token: string;
  ready: boolean;
  logout: () => void;
} {
  const [token, setToken] = useState("");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const sync = () => setToken(readAdminToken());
    sync();
    setReady(true);
    window.addEventListener(TOKEN_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(TOKEN_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const logout = useCallback(() => clearAdminToken(), []);
  return { token, ready, logout };
}
