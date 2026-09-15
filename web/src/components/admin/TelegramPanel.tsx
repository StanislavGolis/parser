"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiDelete, apiPost, apiSend } from "@/lib/api";
import { useAdminToken } from "@/lib/adminAuth";
import { mediaUrl } from "@/lib/env";
import { formatNumber, parseUtc } from "@/lib/format";
import type {
  TelegramCandidate,
  TelegramDigest,
  TelegramPostItem,
  TelegramPostList,
  TelegramPreview,
  TelegramStatus,
} from "@/lib/types";

const MAX_TILES = 4;
const KINDS: Array<{ value: string; label: string; hint: string }> = [
  { value: "teaser", label: "свежее", hint: "подборка новых файлов" },
  { value: "digest", label: "топ", hint: "лучшее за период" },
  { value: "announce", label: "анонс", hint: "текст без картинки или с ней" },
];
const STATUSES: Array<{ value: string; label: string }> = [
  { value: "all", label: "Все" },
  { value: "published", label: "Опубликовано" },
  { value: "failed", label: "Ошибка" },
  { value: "deleted", label: "Удалено" },
];

function errText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return err.detail;
  return err instanceof Error ? err.message : "Ошибка";
}

function when(iso: string | null): string {
  if (!iso) return "—";
  const time = parseUtc(iso);
  return Number.isFinite(time) ? new Date(time).toLocaleString("ru-RU") : "—";
}

/**
 * Менеджер Telegram-канала: композер тизера и журнал публикаций.
 *
 * Публикация ручная: админ выбирает до четырёх файлов, смотрит предпросмотр (текст
 * и собранная картинка), затем отправляет пост в канал. Каждая отправка попадает в
 * журнал — с ошибкой, если Telegram не принял, и кнопкой «повторить».
 */
export default function TelegramPanel() {
  const { token, logout } = useAdminToken();
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [items, setItems] = useState<TelegramCandidate[] | null>(null);
  const [log, setLog] = useState<TelegramPostList | null>(null);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [kind, setKind] = useState("teaser");
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<number[]>([]);
  const [mode, setMode] = useState("mosaic");
  const [blur, setBlur] = useState(7);
  const [buttonText, setButtonText] = useState("");
  const [preview, setPreview] = useState<TelegramPreview | null>(null);
  const [digestPeriod, setDigestPeriod] = useState("day");
  // Пусто — публикуем сразу; иначе пост встаёт в очередь на это время
  const [scheduledFor, setScheduledFor] = useState("");

  const body = useCallback(
    () => ({
      kind,
      text: text.trim() || undefined,
      media_ids: picked,
      image_mode: mode,
      blur,
      button_text: buttonText.trim() || undefined,
      period: kind === "digest" ? digestPeriod : undefined,
      scheduled_at: scheduledFor ? new Date(scheduledFor).toISOString() : undefined,
    }),
    [kind, text, picked, mode, blur, buttonText, digestPeriod, scheduledFor],
  );

  const loadLog = useCallback(
    async (t: string, statusFilter: string) => {
      try {
        const qs = new URLSearchParams({ status: statusFilter, per_page: "30" });
        setLog(await apiSend<TelegramPostList>(`/api/v1/admin/telegram/posts?${qs}`, { token: t }));
        setError(null);
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) logout();
        else setError(errText(err));
      }
    },
    [logout],
  );

  useEffect(() => {
    if (!token) return;
    void apiSend<TelegramStatus>("/api/v1/admin/telegram/status", { token })
      .then((data) => {
        setStatus(data);
        setBlur(data.default_blur);
      })
      .catch((err) => setError(errText(err)));
    void apiSend<TelegramCandidate[]>("/api/v1/admin/telegram/candidates?limit=24", { token })
      .then(setItems)
      .catch((err) => setError(errText(err)));
    void loadLog(token, "all");
  }, [token, loadLog]);

  useEffect(() => {
    if (token) void loadLog(token, filter);
  }, [token, filter, loadLog]);

  function toggle(id: number) {
    setPicked((prev) => {
      if (prev.includes(id)) return prev.filter((item) => item !== id);
      if (prev.length >= MAX_TILES) return prev;
      return [...prev, id];
    });
    setPreview(null);
  }

  /** Дайджест: подставляем подборку (топ за сутки/неделю) и её подпись. */
  async function pickDigest(period: string) {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      const data = await apiSend<TelegramDigest>(
        `/api/v1/admin/telegram/digest?period=${period}`,
        { token },
      );
      setDigestPeriod(period);
      setKind("digest");
      setPicked(data.media_ids);
      setPreview(null);
      if (data.media_ids.length === 0) setError("Для дайджеста не нашлось подходящих файлов");
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function runPreview() {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      setPreview(
        await apiPost<TelegramPreview>("/api/v1/admin/telegram/preview", body(), token),
      );
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function publish() {
    if (!token) return;
    const queued = Boolean(scheduledFor);
    const ask = queued
      ? `Поставить пост в очередь на ${new Date(scheduledFor).toLocaleString()}?`
      : `Опубликовать пост в канал @${status?.channel ?? "?"}?`;
    if (!window.confirm(ask)) return;
    setBusy(true);
    setError(null);
    try {
      const post = await apiPost<TelegramPostItem>("/api/v1/admin/telegram/post", body(), token);
      // `scheduled` — пост в очереди, его отправит планировщик (telegram-publisher)
      if (post.status !== "published" && post.status !== "scheduled") {
        setError(post.error ?? "Публикация не удалась");
      }
      await loadLog(token, filter);
    } catch (err) {
      setError(errText(err));
      await loadLog(token, filter);
    } finally {
      setBusy(false);
    }
  }

  async function retry(post: TelegramPostItem) {
    if (!token) return;
    setBusy(true);
    try {
      await apiPost(`/api/v1/admin/telegram/posts/${post.id}/retry`, undefined, token);
      await loadLog(token, filter);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(post: TelegramPostItem) {
    if (!token) return;
    if (!window.confirm("Удалить сообщение из канала?")) return;
    setBusy(true);
    try {
      await apiDelete(`/api/v1/admin/telegram/posts/${post.id}`, token);
      await loadLog(token, filter);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {/* Композер */}
      {status && !status.configured ? (
        <div className="mb-4 rounded border border-accent-warning/40 bg-ink-secondary px-3 py-2 text-sm text-accent-warning">
          Публикация не настроена: нужны `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHANNEL`, а бот — администратор канала.
        </div>
      ) : null}

      {status?.configured ? (
        <p className="mb-4 font-mono text-[11px] text-text-muted">
          канал: @{status.channel} · бот: @{status.bot}
        </p>
      ) : null}

      <div className="rounded border border-line bg-ink-secondary p-3">
        <div className="flex flex-wrap items-center gap-2">
          {KINDS.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => {
                setKind(item.value);
                setPreview(null);
              }}
              className={`rounded border px-2.5 py-1 text-xs transition-colors ${
                kind === item.value
                  ? "border-accent-primary bg-accent-primary/10 text-accent-primary"
                  : "border-line text-text-secondary hover:text-text-primary"
              }`}
              title={item.hint}
            >
              {item.label}
            </button>
          ))}
          <span className="ml-auto font-mono text-[11px] text-text-muted">
            файлов выбрано: {picked.length}/{MAX_TILES}
          </span>
        </div>

        <textarea
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setPreview(null);
          }}
          rows={3}
          placeholder="Необязательный текст: что нового, анонс, приглашение в бота"
          className="mt-3 w-full rounded border border-line bg-ink-tertiary px-2.5 py-2 text-xs text-text-primary outline-none focus:border-accent-primary"
        />

        {/* Файлы для тизера: порядок плиток = порядок выбора */}
        <div className="mt-3 grid max-h-64 grid-cols-4 gap-1 overflow-y-auto pr-1 sm:grid-cols-6 lg:grid-cols-8">
          {(items ?? []).map((candidate) => {
            const index = picked.indexOf(candidate.id);
            const active = index >= 0;
            return (
              <button
                key={candidate.id}
                type="button"
                onClick={() => toggle(candidate.id)}
                title={candidate.board_slug ? `/${candidate.board_slug} — в тизер` : "в тизер"}
                className={`relative aspect-square overflow-hidden rounded border transition-colors ${
                  active ? "border-accent-primary" : "border-line hover:border-line-hover"
                }`}
              >
                {candidate.thumb_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={mediaUrl(candidate.thumb_url)}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    referrerPolicy="no-referrer"
                    className={`h-full w-full object-cover transition-opacity ${
                      active ? "opacity-100" : "opacity-70 hover:opacity-100"
                    }`}
                  />
                ) : null}
                {active ? (
                  <span className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded bg-accent-primary font-mono text-[11px] font-bold text-ink-primary">
                    {index + 1}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-text-secondary">
          <label className="flex items-center gap-1.5">
            картинка:
            <select
              value={mode}
              onChange={(e) => {
                setMode(e.target.value);
                setPreview(null);
              }}
              className="rounded border border-line bg-ink-tertiary px-2 py-1 text-xs text-text-primary outline-none"
            >
              <option value="mosaic">мозаика 2×2</option>
              <option value="single">один кадр</option>
              <option value="none">без картинки</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5" title="Размытие: канал должен оставаться «мягким»">
            размытие: {blur}
            <input
              type="range"
              min={0}
              max={16}
              value={blur}
              onChange={(e) => setBlur(Number(e.target.value))}
            />
          </label>
          <label className="flex items-center gap-1.5">
            кнопка:
            <input
              value={buttonText}
              onChange={(e) => setButtonText(e.target.value)}
              placeholder="Открыть в боте"
              className="w-40 rounded border border-line bg-ink-tertiary px-2 py-1 text-xs text-text-primary outline-none focus:border-accent-primary"
            />
          </label>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-text-secondary">
          <span className="font-mono text-[11px] text-text-muted">дайджест:</span>
          <button
            type="button"
            onClick={() => void pickDigest("day")}
            disabled={busy}
            className="btn-ghost px-2.5 py-1 text-xs"
            title="Топ архива за сутки: подставит файлы и подпись"
          >
            за сутки
          </button>
          <button
            type="button"
            onClick={() => void pickDigest("week")}
            disabled={busy}
            className="btn-ghost px-2.5 py-1 text-xs"
            title="Топ архива за неделю: подставит файлы и подпись"
          >
            за неделю
          </button>
          <label className="flex items-center gap-1.5">
            опубликовать в:
            <input
              type="datetime-local"
              value={scheduledFor}
              onChange={(e) => setScheduledFor(e.target.value)}
              className="rounded border border-line bg-ink-tertiary px-2 py-1 text-xs text-text-primary outline-none focus:border-accent-primary"
            />
          </label>
          {scheduledFor ? (
            <button
              type="button"
              onClick={() => setScheduledFor("")}
              className="text-text-muted hover:text-text-primary"
            >
              отменить очередь
            </button>
          ) : null}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void runPreview()}
            disabled={busy}
            className="btn-ghost px-3 py-1.5 text-xs"
          >
            Предпросмотр
          </button>
          <button
            type="button"
            onClick={() => void publish()}
            disabled={busy || !status?.configured}
            className="btn-primary px-3 py-1.5 text-xs"
          >
            {scheduledFor ? "Поставить в очередь" : "Опубликовать в канал"}
          </button>
          {error ? <span className="text-xs text-accent-danger">{error}</span> : null}
        </div>

        {preview ? (
          <div className="mt-3 grid gap-3 border-t border-line pt-3 sm:grid-cols-2">
            {preview.image_data_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={preview.image_data_url}
                alt="Предпросмотр тизера"
                className="w-full rounded border border-line"
              />
            ) : (
              <div className="text-xs text-text-muted">
                Картинки не будет — пост уйдёт текстом.
              </div>
            )}
            <pre className="whitespace-pre-wrap rounded border border-line bg-ink-tertiary p-2 font-mono text-[11px] leading-relaxed text-text-secondary">
              {preview.caption}
            </pre>
          </div>
        ) : null}

      </div>

      {/* Журнал публикаций */}
      <div className="mt-6 flex flex-wrap items-center gap-2">
        {STATUSES.map((item) => {
          const count = log?.counts?.[item.value];
          return (
            <button
              key={item.value}
              type="button"
              onClick={() => setFilter(item.value)}
              className={`rounded border px-2.5 py-1 font-mono text-[11px] transition-colors ${
                filter === item.value
                  ? "border-accent-primary bg-accent-primary/10 text-accent-primary"
                  : "border-line text-text-secondary hover:text-text-primary"
              }`}
            >
              {item.label}
              {count !== undefined ? ` ${formatNumber(count)}` : ""}
            </button>
          );
        })}
      </div>

      {log && log.items.length === 0 ? (
        <p className="py-8 text-center text-sm text-text-secondary">
          Публикаций пока нет — соберите первый пост в композере выше.
        </p>
      ) : null}

      <div className="mt-3 flex flex-col gap-2">
        {(log?.items ?? []).map((post) => (
          <div
            key={post.id}
            className={`rounded border bg-ink-secondary p-3 ${
              post.status === "failed" ? "border-accent-danger/50" : "border-line"
            }`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`badge ${
                  post.status === "published"
                    ? "badge-ok"
                    : post.status === "failed"
                      ? "border-accent-danger text-accent-danger"
                      : "badge-muted"
                }`}
              >
                {post.status}
              </span>
              <span className="font-mono text-[11px] text-text-muted">
                #{post.id} · {post.kind} · {post.image_mode}
              </span>
              {post.status === "scheduled" ? (
                <span className="font-mono text-[11px] text-accent-primary">
                  в очереди на {when(post.scheduled_at)}
                </span>
              ) : null}
              <span className="font-mono text-[11px] text-text-muted">
                {when(post.published_at ?? post.created_at)}
              </span>
              {post.link ? (
                <a
                  href={post.link}
                  target="_blank"
                  rel="noreferrer"
                  className="font-mono text-[11px] text-accent-primary hover:underline"
                >
                  сообщение в канале ↗
                </a>
              ) : null}
              <span className="ml-auto flex items-center gap-2">
                {post.status !== "published" ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void retry(post)}
                    className="btn-ghost px-2 py-1 text-[11px]"
                  >
                    повторить
                  </button>
                ) : null}
                {post.status === "published" ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void remove(post)}
                    className="rounded border border-accent-danger/40 px-2 py-0.5 text-[11px] text-accent-danger transition-colors hover:border-accent-danger"
                  >
                    удалить из канала
                  </button>
                ) : null}
              </span>
            </div>

            <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-text-secondary">
              {post.caption}
            </pre>
            {post.error ? <p className="mt-1 text-xs text-accent-danger">{post.error}</p> : null}
            {post.media_ids?.length ? (
              <p className="mt-1 font-mono text-[10px] text-text-muted">
                файлы: {post.media_ids.join(", ")}
              </p>
            ) : null}
          </div>
        ))}
      </div>


    </div>
  );
}
