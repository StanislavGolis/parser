"use client";

import { ApiError, apiDelete, apiGet, apiPost } from "@/lib/api";

/**
 * «Продолжить просмотр»: последний файл, который зритель смотрел в треде.
 *
 * Анониму точку хранит localStorage браузера — без аккаунта и без сервера, поэтому
 * она переживает закрытие сайта и возвращение через день. Авторизованному точку
 * дополнительно хранит сервер (`POST /api/v1/resume`): сменил устройство — тред
 * открывается на том же файле (см. `syncResumes`).
 *
 * Если хранилище недоступно (приватный режим, запрет хранения в браузере),
 * функции молча ничего не делают: фича деградирует, сайт не ломается.
 */

const KEY = "dredge.resume.v2";
/** Сколько тредов помним: более старые вытесняются по времени просмотра. */
const MAX_THREADS = 200;
/** Старше этого срока точка возврата считается забытой. */
const MAX_AGE_MS = 60 * 24 * 60 * 60 * 1000; // 60 дней

export interface ResumePoint {
  /** id файла, на котором зритель остановился (главный ориентир). */
  id: number;
  /** Позиция файла в списке треда на момент сохранения (0-based). */
  index: number;
  /**
   * Сколько файлов **в треде** было на момент просмотра (не размер порции!).
   * Именно по нему считается «+N новых в конце».
   */
  total: number;
  /**
   * `true` — `total` это размер треда (точный). Старые записи формата v1 хранили
   * размер загруженной порции (300) и давали ложные «+582 новых», поэтому такие
   * точки игнорируются (см. `v1` → `v2` в ключе хранилища).
   */
  exact?: boolean;
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
    // Следы старого формата (v1): он хранил размер загруженной порции вместо
    // размера треда и давал ложные «+N новых в конце» — убираем раз и навсегда.
    localStorage.removeItem("dredge.resume.v1");
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

/** Запоминает карту в хранилище (с вытеснением старых тредов). */
function writeMap(map: ResumeMap): void {
  const store = storage();
  if (!store) return;

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
  // `total` — размер треда на момент просмотра (передаёт вызывающий, а не размер
  // загруженной порции): иначе «+N новых в конце» считалось бы неверно.
  map[key(threadId)] = { id: mediaId, index, total, exact: true, at: Date.now() };
  writeMap(map);

  // Авторизованным — та же точка в БД, чтобы она не терялась при смене устройства
  void pushResume(threadId, mediaId, index, total);
}

/** Забыть точку возврата треда («начать сначала»). */
export function clearResume(threadId: number): void {
  const store = storage();
  if (!store) return;
  const map = readResumes();
  if (!(key(threadId) in map)) return;
  delete map[key(threadId)];
  writeMap(map);

  // И на сервере, если пользователь вошёл (анониму отвечать нечего)
  void pushForgetResume(threadId);
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

// ─────────────── Синхронизация с сервером (аккаунт) ───────────────

/** Точка возврата в ответе API: `index` — позиция в списке треда. */
interface ServerResumePoint {
  thread_id: number;
  media_id: number;
  index: number;
  total: number;
  updated_at: string;
}

/**
 * `null` — ещё не выяснили, `false` — зритель анонимный (не дёргаем API зря),
 * `true` — синхронизация работает.
 */
let serverEnabled: boolean | null = null;

function serverThreadFromKey(mapKey: string): number {
  const id = Number(mapKey.slice(1));
  return Number.isFinite(id) ? id : 0;
}

/** Отправляет точку на сервер (для анонима тихо отключается). */
async function pushResume(
  threadId: number,
  mediaId: number,
  index: number,
  total: number,
): Promise<void> {
  if (serverEnabled === false) return;
  try {
    await apiPost("/api/v1/resume", {
      thread_id: threadId,
      media_id: mediaId,
      index,
      total,
    });
    serverEnabled = true;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) serverEnabled = false;
  }
}

/** Удаляет точку на сервере («забыть»). */
async function pushForgetResume(threadId: number): Promise<void> {
  if (serverEnabled === false) return;
  try {
    await apiDelete(`/api/v1/resume/${threadId}`);
    serverEnabled = true;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) serverEnabled = false;
  }
}

/**
 * Подтягивает точки аккаунта с сервера и сливает их с локальными.
 *
 * Правила слияния:
 * * серверная точка свежее локальной — берём серверную (это случай «смотрели
 *   на другом устройстве»);
 * * локальные точки, которых нет на сервере, — догоняем (`pushResume`): так
 *   просмотр до входа тоже становится общей точкой.
 *
 * Для анонима запрос один раз вернёт 401 — синхронизация отключается до
 * перезагрузки страницы, и всё работает как раньше (только localStorage).
 */
export async function syncResumes(): Promise<void> {
  if (serverEnabled === false) return;

  let payload: { items?: ServerResumePoint[] };
  try {
    payload = await apiGet<{ items?: ServerResumePoint[] }>("/api/v1/resume");
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) serverEnabled = false;
    return;
  }
  serverEnabled = true;

  const onServer = new Set<number>();
  const map = readResumes();
  let changed = false;

  for (const item of payload.items ?? []) {
    if (!Number.isFinite(item?.thread_id) || !Number.isFinite(item?.media_id)) continue;
    onServer.add(item.thread_id);

    const serverAt = Date.parse(item.updated_at);
    const local = map[key(item.thread_id)];
    if (!local || !Number.isFinite(local.at) || serverAt > local.at) {
      map[key(item.thread_id)] = {
        id: item.media_id,
        index: item.index,
        total: item.total,
        exact: true,
        at: Number.isFinite(serverAt) ? serverAt : Date.now(),
      };
      changed = true;
    }
  }

  if (changed) writeMap(map);

  // Догоняем сервер локальными точками, которых там ещё нет
  for (const [mapKey, point] of Object.entries(map)) {
    const threadId = serverThreadFromKey(mapKey);
    if (!threadId || onServer.has(threadId)) continue;
    await pushResume(threadId, point.id, point.index, point.total);
  }
}

