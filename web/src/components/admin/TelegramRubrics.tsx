"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiPatch, apiPost, apiSend } from "@/lib/api";
import { useAdminToken } from "@/lib/adminAuth";
import { parseUtc } from "@/lib/format";
import type { TelegramRubric, TelegramRubricPreview } from "@/lib/types";

/** Что делает рубрика — короткая подсказка в карточке. */
const HINTS: Record<string, string> = {
  fresh:
    "Мозаика 2×2 из свежих файлов, список разделов с приростом за сутки и по одному фото из каждого раздела в хорошем качестве.",
  board_day:
    "Несколько фото из одного треда раздела, число файлов в разделе и его описание из админки.",
  top_week:
    "Мозаика 2×2 и разделы, которые смотрели и сохраняли за период: объём раздела и прирост.",
};

/** Числовые параметры по коду рубрики: подпись и границы. */
const NUMBER_FIELDS: Record<
  string,
  Array<{ key: string; label: string; min: number; max: number }>
> = {
  fresh: [
    { key: "hours", label: "период, ч", min: 1, max: 336 },
    { key: "boards_count", label: "разделов в тексте", min: 1, max: 6 },
    { key: "board_photos", label: "фото разделов (0 — только мозаика)", min: 0, max: 6 },
    { key: "tiles", label: "плиток мозаики", min: 1, max: 4 },
    { key: "blur", label: "размытие (0–24)", min: 0, max: 24 },
  ],
  board_day: [
    { key: "photos", label: "фото из треда", min: 1, max: 10 },
    { key: "blur", label: "размытие (0–24, 0 — как есть)", min: 0, max: 24 },
  ],
  top_week: [
    { key: "days", label: "период, дн.", min: 2, max: 30 },
    { key: "boards_count", label: "разделов", min: 1, max: 6 },
    { key: "tiles", label: "плиток мозаики", min: 1, max: 4 },
    { key: "blur", label: "размытие (0–24)", min: 0, max: 24 },
  ],
};

const SORT_MODES: Array<{ value: string; label: string }> = [
  { value: "activity", label: "что смотрели и сохраняли" },
  { value: "growth", label: "прирост файлов" },
  { value: "size", label: "объём раздела" },
];

const QUALITIES: Array<{ value: string; label: string }> = [
  { value: "web", label: "хорошее качество (web)" },
  { value: "thumb", label: "превью (thumb)" },
];

const IMAGE_MODES: Record<string, string> = {
  album: "альбом: мозаика + фото",
  mosaic: "одно фото-мозаика",
  single: "одно фото",
  none: "без картинки",
};

function errText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return err instanceof Error ? err.message : "Не получилось";
}

/** Дата и время по-человечески: «16.09 19:40». */
function when(iso: string | null): string {
  if (!iso) return "—";
  const time = new Date(parseUtc(iso));
  if (Number.isNaN(time.getTime())) return "—";
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(time.getDate())}.${pad(time.getMonth() + 1)} ${pad(time.getHours())}:${pad(time.getMinutes())}`;
}

/** Подпись без HTML-тегов — для предпросмотра в админке. */
function plain(caption: string): string {
  return caption.replace(/<[^>]+>/g, "");
}

function asNumber(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function asText(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

/**
 * Рубрики автопоста: «Свежее», «Раздел дня», «Топ недели».
 *
 * Планировщик сам выбирает, какая рубрика выйдет следующей (по паузе между постами,
 * см. блок «Автопостинг»), а здесь её включают, настраивают параметры и проверяют
 * предпросмотр ровно того поста, который уйдёт в канал.
 */
export default function TelegramRubrics() {
  const { token, logout } = useAdminToken();
  const [items, setItems] = useState<TelegramRubric[] | null>(null);
  const [previews, setPreviews] = useState<Record<string, TelegramRubricPreview>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  // Черновик поля «раздел» у «Раздела дня»: сохраняем по выходу из поля
  const [boardDrafts, setBoardDrafts] = useState<Record<string, string>>({});

  const guard = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) logout();
      else setError(errText(err));
    },
    [logout],
  );

  const load = useCallback(
    async (t: string) => {
      try {
        setItems(await apiSend<TelegramRubric[]>("/api/v1/admin/telegram/rubrics", { token: t }));
        setError(null);
      } catch (err) {
        guard(err);
      }
    },
    [guard],
  );

  useEffect(() => {
    if (token) void load(token);
  }, [token, load]);

  async function save(code: string, patch: Record<string, unknown>) {
    if (!token) return;
    setBusy(code);
    setError(null);
    try {
      await apiPatch<TelegramRubric>(`/api/v1/admin/telegram/rubrics/${code}`, patch, token);
      await load(token);
    } catch (err) {
      guard(err);
    } finally {
      setBusy("");
    }
  }

  async function saveOption(code: string, key: string, value: unknown) {
    await save(code, { options: { [key]: value } });
  }

  async function showPreview(code: string) {
    if (!token) return;
    setBusy(code);
    setError(null);
    try {
      const data = await apiPost<TelegramRubricPreview>(
        `/api/v1/admin/telegram/rubrics/${code}/preview`,
        undefined,
        token,
      );
      setPreviews((prev) => ({ ...prev, [code]: data }));
    } catch (err) {
      guard(err);
    } finally {
      setBusy("");
    }
  }

  async function runNow(item: TelegramRubric, publish: boolean) {
    if (!token) return;
    const question = publish
      ? `Собрать «${item.title}» и сразу опубликовать в канале?`
      : `Собрать «${item.title}» и отправить черновик вам в ЛС бота?`;
    if (!window.confirm(question)) return;
    setBusy(item.code);
    setError(null);
    try {
      const post = await apiPost<{ id: number; status: string }>(
        `/api/v1/admin/telegram/rubrics/${item.code}/run${publish ? "?publish=true" : ""}`,
        undefined,
        token,
      );
      window.alert(
        post.status === "published"
          ? "Пост ушёл в канал."
          : "Черновик отправлен вам в ЛС бота: подтвердите или отклоните его там.",
      );
      await load(token);
    } catch (err) {
      guard(err);
    } finally {
      setBusy("");
    }
  }

  const field =
    "rounded border border-line bg-ink-tertiary px-2 py-1 text-xs text-text-primary outline-none focus:border-accent-primary";

  return (
    <div className="rounded border border-line bg-ink-secondary p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Рубрики автопоста</h3>
        <span className="font-mono text-[11px] text-text-muted">
          планировщик берёт рубрику с самой большой паузой
        </span>
      </div>
      <p className="mt-1 text-xs text-text-secondary">
        Каждая рубрика — свой тип поста в канале: включайте нужные и настраивайте
        параметры. По умолчанию всё уходит в карантин — черновик приходит вам в ЛС бота.
      </p>

      {error ? <p className="mt-2 text-xs text-accent-danger">{error}</p> : null}

      <div className="mt-3 flex flex-col gap-3">
        {(items ?? []).map((item) => {
          const options = item.effective ?? {};
          const preview = previews[item.code];
          const paused = item.reason === "пауза между постами";
          return (
            <div key={item.code} className="rounded border border-line bg-ink-tertiary p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="text-sm font-semibold">{item.title}</span>
                  <span className="font-mono text-[11px] text-text-muted">{item.code}</span>
                  <span
                    className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
                      item.enabled
                        ? "bg-accent-primary/15 text-accent-primary"
                        : "bg-ink-secondary text-text-muted"
                    }`}
                  >
                    {item.enabled ? "включена" : "выключена"}
                  </span>
                  <span className="font-mono text-[11px] text-text-muted">
                    последний раз: {when(item.last_run_at)}
                    {paused ? ` · следующий выход после ${when(item.next_run_at)}` : ""}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void save(item.code, { enabled: !item.enabled })}
                    disabled={busy === item.code}
                    className={
                      item.enabled
                        ? "btn-ghost px-2.5 py-1 text-xs"
                        : "btn-primary px-2.5 py-1 text-xs"
                    }
                  >
                    {item.enabled ? "Выключить" : "Включить"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void showPreview(item.code)}
                    disabled={busy === item.code}
                    className="btn-ghost px-2.5 py-1 text-xs"
                  >
                    Предпросмотр
                  </button>
                  <button
                    type="button"
                    onClick={() => void runNow(item, false)}
                    disabled={busy === item.code}
                    className="btn-ghost px-2.5 py-1 text-xs"
                  >
                    Собрать сейчас
                  </button>
                  <button
                    type="button"
                    onClick={() => void runNow(item, true)}
                    disabled={busy === item.code}
                    className="btn-ghost px-2.5 py-1 text-xs"
                  >
                    В канал сразу
                  </button>
                </div>
              </div>

              <p className="mt-1.5 text-xs text-text-secondary">{HINTS[item.code] ?? ""}</p>

              {/* Настройки рубрики */}
              <div className="mt-2.5 flex flex-wrap items-end gap-x-4 gap-y-2 text-xs text-text-secondary">
                <label className="flex items-center gap-1.5">
                  не чаще, чем раз в
                  <input
                    type="number"
                    min={1}
                    max={720}
                    value={item.min_gap_hours}
                    onChange={(e) =>
                      void save(item.code, { min_gap_hours: Number(e.target.value) })
                    }
                    className={`${field} w-16`}
                  />
                  ч
                </label>
                {(NUMBER_FIELDS[item.code] ?? []).map((row) => (
                  <label key={row.key} className="flex items-center gap-1.5">
                    {row.label}:
                    <input
                      type="number"
                      min={row.min}
                      max={row.max}
                      value={asNumber(options[row.key], row.min)}
                      onChange={(e) => void saveOption(item.code, row.key, Number(e.target.value))}
                      className={`${field} w-16`}
                    />
                  </label>
                ))}
                <label className="flex items-center gap-1.5">
                  качество:
                  <select
                    value={asText(options.quality, "web")}
                    onChange={(e) => void saveOption(item.code, "quality", e.target.value)}
                    className={field}
                  >
                    {QUALITIES.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </label>
                {item.code === "board_day" ? (
                  <label className="flex items-center gap-1.5">
                    раздел (пусто — ротация):
                    <input
                      value={boardDrafts[item.code] ?? asText(options.board)}
                      placeholder="asmr"
                      onChange={(e) =>
                        setBoardDrafts((prev) => ({ ...prev, [item.code]: e.target.value }))
                      }
                      onBlur={(e) => void saveOption(item.code, "board", e.target.value.trim())}
                      className={`${field} w-32`}
                    />
                  </label>
                ) : null}
                {item.code === "top_week" ? (
                  <label className="flex items-center gap-1.5">
                    сортировка:
                    <select
                      value={asText(options.sort, "activity")}
                      onChange={(e) => void saveOption(item.code, "sort", e.target.value)}
                      className={field}
                    >
                      {SORT_MODES.map((mode) => (
                        <option key={mode.value} value={mode.value}>
                          {mode.label}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
              </div>

              {/* Предпросмотр: текст и кадры ровно того поста, что уйдёт в канал */}
              {preview ? (
                <div className="mt-3 rounded border border-line bg-ink-secondary p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs font-semibold">Предпросмотр</span>
                    <span className="font-mono text-[11px] text-text-muted">
                      {IMAGE_MODES[preview.image_mode] ?? preview.image_mode}
                      {preview.board ? ` · раздел /${preview.board}` : ""}
                      {preview.note ? ` · ${preview.note}` : ""}
                    </span>
                  </div>
                  {preview.images.length ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {preview.images.map((src, index) => (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          key={index}
                          src={src}
                          alt=""
                          className="h-28 w-auto rounded border border-line"
                        />
                      ))}
                    </div>
                  ) : null}
                  <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-text-secondary">
                    {plain(preview.caption) || "Пусто: нечего показать"}
                  </pre>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

