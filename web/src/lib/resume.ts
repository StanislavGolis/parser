"use client";

/**
 * «Продолжить просмотр»: последний файл, который зритель смотрел в треде.
 *
 * Хранится в localStorage браузера — без аккаунта, без cookie и без сервера,
 * поэтому точка возврата переживает закрытие сайта и возвращение через день.
 * Если хранилище недоступно (приватный режим, запрет хранения в браузере),
 * функции молча ничего не делают: фича деградирует, сайт не ломается.
 */

const KEY = "dredge.resume.v1";
/** Сколько тредов помним: более старые вытесняются по времени просмотра. */
const MAX_THREADS = 200;
/** Старше этого срока точка возврата считается забытой. */
const MAX_AGE_MS = 60 * 24 * 60 * 60 * 1000; // 60 дней

export interface ResumePoint {
  /** id файла, на котором зритель остановился (главный ориентир). */
  id: number;
  /** Позиция файла в списке треда на момент сохранения (0-based). */
  index: number;
  /** Сколько файлов было в том списке — понятно, изменился ли он. */
  total: number;
  /** Когда смотрели (мс) — для «5 мин назад» и вытеснения старых записей. */
  at: number;
}

/** Карта «t{thread_id} → точка возврата». */
export type ResumeMap = Record<string, ResumePoint>;

function storage(): Storage | null {
  try {
    if (typeof localStorage === "undefined") return null;
    // Проверяем записью: в приватном режиме/при запрете storage бросает ошибку
    const probe = "__dredge_probe__";
    localStorage.setItem(probe, "1");
    localStorage.removeItem(probe);
    return localStorage;
  } catch {
    return null;
  }
}

function key(threadId: number): string {
  return `t${threadId}`;
}

function isPoint(value: unknown): value is ResumePoint {
  if (typeof value !== "object" || value === null) return false;
  const p = value as Partial<ResumePoint>;
  return (
    Number.isFinite(p.id) &&
    Number.isFinite(p.index) &&
    Number.isFinite(p.total) &&
    Number.isFinite(p.at)
  );
}

/** Читает карту целиком, отбрасывая испорченные и устаревшие записи. */
export function readResumes(): ResumeMap {
  const store = storage();
  if (!store) return {};
  let parsed: unknown;
  try {
    const raw = store.getItem(KEY);
    if (!raw) return {};
    parsed = JSON.parse(raw);
  } catch {
    return {};
  }
  if (typeof parsed !== "object" || parsed === null) return {};

  const now = Date.now();
  const fresh: ResumeMap = {};
  for (const [k, value] of Object.entries(parsed as Record<string, unknown>)) {
    // чужой/битый формат и давние записи не храним
    if (!isPoint(value) || now - value.at > MAX_AGE_MS) continue;
    fresh[k] = value;
  }
  return fresh;
}

/** Точка возврата для треда (или null, если её нет). */
export function getResume(threadId: number): ResumePoint | null {
  return readResumes()[key(threadId)] ?? null;
}

/** Запомнить «смотрели этот файл треда». */
export function saveResume(
  threadId: number,
  mediaId: number,
  index: number,
  total: number,
): void {
  const store = storage();
  if (!store || !threadId || !mediaId) return;

  const map = readResumes();
  map[key(threadId)] = { id: mediaId, index, total, at: Date.now() };

  // Вытеснение: держим только MAX_THREADS самых свежих тредов
  const entries = Object.entries(map);
  if (entries.length > MAX_THREADS) {
    entries.sort((a, b) => b[1].at - a[1].at);
    for (const [k] of entries.slice(MAX_THREADS)) delete map[k];
  }

  try {
    store.setItem(KEY, JSON.stringify(map));
  } catch {
    /* переполнение хранилища — не повод ломать просмотр */
  }
}

/** Забыть точку возврата треда («начать сначала»). */
export function clearResume(threadId: number): void {
  const store = storage();
  if (!store) return;
  const map = readResumes();
  if (!(key(threadId) in map)) return;
  delete map[key(threadId)];
  try {
    store.setItem(KEY, JSON.stringify(map));
  } catch {
    /* см. saveResume */
  }
}

/**
 * Индекс файла, с которого продолжать просмотр.
 * Сначала ищем тот же файл по id (файлы между визитами появляются и удаляются),
 * и только если его больше нет — используем сохранённую позицию, но лишь при том
 * же размере списка (иначе позиция ничего не значит и начинаем сначала).
 */
export function resumeIndex(
  point: ResumePoint | null,
  items: Array<{ id: number }>,
): number {
  if (!point || items.length === 0) return 0;
  const byId = items.findIndex((m) => m.id === point.id);
  if (byId >= 0) return byId;
  if (point.total === items.length && point.index >= 0 && point.index < items.length) {
    return point.index;
  }
  return 0;
}
