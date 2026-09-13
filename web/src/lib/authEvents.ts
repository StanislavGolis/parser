"use client";

/**
 * Единое событие смены авторизации: вход и выход видны всем компонентам.
 *
 * `router.refresh()` перерисовывает серверные компоненты, но клиентские
 * (`AuthMenu` в шапке) хранят своё состояние в `useState` и о входе не узнают —
 * из-за этого после входа имя профиля появлялось только после перезагрузки.
 */

export const AUTH_EVENT = "dredge:auth";

/** Сообщает интерфейсу, что статус входа изменился. */
export function notifyAuthChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(AUTH_EVENT));
}

/** Подписка на смену статуса входа (возвращает функцию отписки). */
export function onAuthChanged(handler: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(AUTH_EVENT, handler);
  return () => window.removeEventListener(AUTH_EVENT, handler);
}
