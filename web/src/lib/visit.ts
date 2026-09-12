// «Новое с прошлого визита»: cookie с моментом последнего просмотра.

/** Cookie последнего визита (ISO 8601, UTC). Пишется на клиенте, читается на сервере. */
export const LAST_VISIT_COOKIE = "dv_last";

/** Год: значение перезаписывается при каждом заходе, но «помним» долго. */
export const LAST_VISIT_MAX_AGE = 60 * 60 * 24 * 365;

const MONTHS = [
  "января",
  "февраля",
  "марта",
  "апреля",
  "мая",
  "июня",
  "июля",
  "августа",
  "сентября",
  "октября",
  "ноября",
  "декабря",
];

/**
 * Разбирает дату визита (cookie или `?since=`) и отсекает мусор:
 * нужен ISO-подобный момент в разумных границах, иначе показывать нечего.
 */
export function parseVisitDate(value: string | undefined | null): Date | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  if (date.getUTCFullYear() < 2000) return null;
  if (date.getTime() > Date.now() + 24 * 60 * 60 * 1000) return null;
  return date;
}

/** Подпись даты для блока «новое с …»: «12 сентября» (UTC, без Intl-зависимостей). */
export function visitLabel(date: Date): string {
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]}`;
}
