/** Форматирование размеров, дат и чисел для UI. */

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 Б";
  const units = ["Б", "КБ", "МБ", "ГБ"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** i;
  return `${value.toFixed(value >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function formatNumber(n: number): string {
  return new Intl.NumberFormat("ru-RU").format(n);
}

function toDate(iso: string): Date {
  // API отдаёт UTC-время без таймзоны — добавляем 'Z', чтобы не трактовать как локальное.
  const s = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`;
  return new Date(s);
}

/** Дата в UTC-представлении — одинакова на сервере и клиенте (для SSR/hydration). */
export function formatUtc(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(toDate(iso));
}

/** Дата в локальной таймзоне пользователя (после гидрации). */
export function formatLocal(iso: string): string {
  const dt = toDate(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(dt);
}

/** Относительная дата «5 мин назад» (вызывать только на клиенте). */
export function formatRelative(iso: string): string {
  const dt = toDate(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  const diffMs = Date.now() - dt.getTime();
  const min = Math.floor(diffMs / 60_000);
  if (min < 1) return "только что";
  if (min < 60) return `${min} мин назад`;
  const hours = Math.floor(min / 60);
  if (hours < 24) return `${hours} ч назад`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} дн назад`;
  return formatLocal(iso);
}

/** Группа медиа для вкладки «все / картинки / видео». */
export function plural(n: number, forms: [string, string, string]): string {
  const abs = Math.abs(n) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) return forms[2];
  if (last > 1 && last < 5) return forms[1];
  if (last === 1) return forms[0];
  return forms[2];
}
