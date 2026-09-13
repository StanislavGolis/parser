/**
 * Настройки показа, которые переживают переходы и перезагрузки.
 *
 * Живут в cookie: их читает и сервер (SSR-фильтрация ленты), и клиент
 * (состояние чекбокса). Так фильтр остаётся личным и не плодит адресов вида
 * `?free=1`, а страницы — ссылочными (canonical остаётся «чистым»).
 */

/** «Скрыть премиум»: убрать из лент файлы, доступные только по подписке. */
export const HIDE_PREMIUM_COOKIE = "dv_hide_premium";
/** Значение «включено» — его же проверяет сервер. */
export const HIDE_PREMIUM_ON = "1";
/** Год: это предпочтение зрителя, а не настройка сессии. */
const MAX_AGE = 365 * 24 * 60 * 60;

/** Клиентское чтение — для состояния чекбокса. */
export function readHidePremium(): boolean {
  if (typeof document === "undefined") return false;
  return document.cookie
    .split("; ")
    .some((part) => part.startsWith(`${HIDE_PREMIUM_COOKIE}=${HIDE_PREMIUM_ON}`));
}

/** Запись настройки (клиент): включение/сброс cookie. */
export function writeHidePremium(on: boolean): void {
  if (typeof document === "undefined") return;
  document.cookie = on
    ? `${HIDE_PREMIUM_COOKIE}=${HIDE_PREMIUM_ON}; path=/; max-age=${MAX_AGE}; samesite=lax`
    : `${HIDE_PREMIUM_COOKIE}=; path=/; max-age=0; samesite=lax`;
}
