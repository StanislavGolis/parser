"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiDelete, apiPatch, apiPost, apiSend } from "@/lib/api";
import { useAdminToken } from "@/lib/adminAuth";
import { mediaUrl } from "@/lib/env";
import { formatNumber, parseUtc } from "@/lib/format";
import type { BlockedHashItem, MediaReportItem, MediaReportList } from "@/lib/types";

const POLL_MS = 15000;

const STATUSES: Array<{ value: string; label: string }> = [
  { value: "open", label: "Открытые" },
  { value: "hidden", label: "Файл скрыт" },
  { value: "thread_hidden", label: "Тред скрыт" },
  { value: "removed", label: "Удалено" },
  { value: "rejected", label: "Отклонено" },
  { value: "all", label: "Все" },
];

/** Причины, по которым доступ закрывается сразу (без ожидания модератора). */
const URGENT = new Set(["csam"]);

function errText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return err.detail;
  return err instanceof Error ? err.message : "Ошибка";
}

function when(iso: string): string {
  const time = parseUtc(iso);
  return Number.isFinite(time) ? new Date(time).toLocaleString("ru-RU") : "—";
}

/**
 * Очередь жалоб и блок-лист хешей.
 *
 * Модератор решает по картинке: в строке жалобы видно миниатюру, раздел и тред, а
 * действия — «скрыть файл», «скрыть тред», «удалить файл», «отклонить». Удаление
 * уносит и объекты в хранилище; каждое действие попадает в журнал админки.
 */
/**
 * Блок-лист хешей: запрещённый контент не публикуется.
 *
 * При добавлении хеша существующие файлы архива с этим SHA-256 скрываются сразу
 * (и их треды), а новые пайплайн сохраняет скрытыми. Снятие хеша не возвращает
 * файлы в ленты — видимость модератор включает вручную в «Контенте».
 */
function BlockedHashes() {
  const { token, logout } = useAdminToken();
  const [items, setItems] = useState<BlockedHashItem[] | null>(null);
  const [sha, setSha] = useState("");
  const [reason, setReason] = useState("csam");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (t: string) => {
      try {
        setItems(await apiSend<BlockedHashItem[]>("/api/v1/admin/blocked-hashes", { token: t }));
        setError(null);
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) logout();
        else setError(errText(err));
      }
    },
    [logout],
  );

  useEffect(() => {
    if (token) void load(token);
  }, [token, load]);

  async function add() {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await apiPost(
        "/api/v1/admin/blocked-hashes",
        { sha256: sha.trim(), reason, note: note.trim() || undefined },
        token,
      );
      setSha("");
      setNote("");
      await load(token);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    if (!token) return;
    if (!window.confirm("Убрать хеш из блок-листа? Скрытые файлы останутся скрытыми.")) return;
    setBusy(true);
    try {
      await apiDelete(`/api/v1/admin/blocked-hashes/${id}`, token);
      await load(token);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="mt-8 rounded border border-line bg-ink-secondary p-3">
      <summary className="cursor-pointer text-sm font-semibold text-text-primary">
        Блок-лист хешей{items ? ` (${formatNumber(items.length)})` : ""}
      </summary>
      <p className="mt-1 text-xs text-text-secondary">
        Файл с таким SHA-256 не публикуется: существующие скрываются сразу, новые
        сохраняются скрытыми. Хеш нужен, чтобы запрещённый файл не вернулся
        пересканированием или импортом из архива.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          value={sha}
          onChange={(e) => setSha(e.target.value)}
          placeholder="sha256 (64 символа hex)"
          className="min-w-72 flex-1 rounded border border-line bg-ink-tertiary px-2 py-1 font-mono text-xs text-text-primary outline-none focus:border-accent-primary"
        />
        <select
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="rounded border border-line bg-ink-tertiary px-2 py-1 text-xs text-text-primary outline-none focus:border-accent-primary"
        >
          <option value="csam">детская безопасность</option>
          <option value="copyright">авторские права</option>
          <option value="other">другое</option>
        </select>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="заметка (откуда хеш)"
          className="min-w-40 flex-1 rounded border border-line bg-ink-tertiary px-2 py-1 text-xs text-text-primary outline-none focus:border-accent-primary"
        />
        <button
          type="button"
          onClick={() => void add()}
          disabled={busy || sha.trim().length !== 64}
          className="btn-primary px-3 py-1 text-xs"
        >
          Добавить
        </button>
      </div>

      {error ? <p className="mt-2 text-xs text-accent-danger">{error}</p> : null}

      {items && items.length > 0 ? (
        <div className="mt-3 flex flex-col gap-1">
          {items.map((item) => (
            <div
              key={item.id}
              className="flex flex-wrap items-center gap-2 rounded border border-line px-2 py-1.5 text-xs"
            >
              <span className="font-mono text-[11px] text-text-secondary" title={item.sha256}>
                {item.sha256.slice(0, 16)}…
              </span>
              <span className="badge badge-muted">{item.reason}</span>
              <span className="text-text-muted">файлов: {formatNumber(item.media_count)}</span>
              {item.note ? (
                <span className="max-w-72 truncate text-text-muted" title={item.note}>
                  {item.note}
                </span>
              ) : null}
              <span className="ml-auto font-mono text-[10px] text-text-muted">
                {when(item.created_at)}
              </span>
              <button
                type="button"
                disabled={busy}
                onClick={() => void remove(item.id)}
                className="rounded border border-accent-danger/40 px-2 py-0.5 text-[11px] text-accent-danger transition-colors hover:border-accent-danger"
              >
                убрать
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-xs text-text-muted">Список пуст.</p>
      )}
    </details>
  );
}

/** Очередь жалоб: фильтры по статусам, разбор каждой и блок-лист хешей. */
export default function ReportsPanel() {
  const { token, logout } = useAdminToken();
  const [data, setData] = useState<MediaReportList | null>(null);
  const [status, setStatus] = useState("open");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});

  const load = useCallback(
    async (t: string, filter: string) => {
      try {
        const qs = new URLSearchParams({ status: filter, per_page: "50" });
        setData(await apiSend<MediaReportList>(`/api/v1/admin/reports?${qs}`, { token: t }));
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
    void load(token, status);
    const id = window.setInterval(() => void load(token, status), POLL_MS);
    return () => window.clearInterval(id);
  }, [token, status, load]);

  async function resolve(item: MediaReportItem, action: string) {
    if (!token) return;
    const note = (notes[item.id] ?? "").trim();
    if (action === "remove_media" && !window.confirm(
      `Удалить файл #${item.media_id} вместе с объектами в хранилище? Действие необратимо.`,
    )) {
      return;
    }
    setBusy(item.id);
    setError(null);
    try {
      await apiPatch(`/api/v1/admin/reports/${item.id}`, { action, note: note || undefined }, token);
      await load(token, status);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {STATUSES.map((s) => {
          const count = data?.counts?.[s.value];
          return (
            <button
              key={s.value}
              type="button"
              onClick={() => setStatus(s.value)}
              className={`rounded border px-2.5 py-1 font-mono text-[11px] transition-colors ${
                status === s.value
                  ? "border-accent-primary bg-accent-primary/10 text-accent-primary"
                  : "border-line text-text-secondary hover:text-text-primary"
              }`}
            >
              {s.label}
              {count !== undefined ? ` ${formatNumber(count)}` : ""}
            </button>
          );
        })}
      </div>

      {error ? (
        <div className="mb-3 rounded border border-accent-danger/30 bg-red-500/5 px-3 py-2 text-sm text-accent-danger">
          {error}
        </div>
      ) : null}

      {!data ? (
        <p className="py-8 text-center text-sm text-text-secondary">Загружаем…</p>
      ) : data.items.length === 0 ? (
        <p className="py-8 text-center text-sm text-text-secondary">
          Жалоб нет — очередь пуста.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {data.items.map((item) => (
            <div
              key={item.id}
              className={`rounded border bg-ink-secondary p-3 ${
                URGENT.has(item.reason) ? "border-accent-danger/60" : "border-line"
              }`}
            >
              <div className="flex gap-3">
                <a
                  href={`/media/${item.media_id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="h-20 w-20 shrink-0 overflow-hidden rounded border border-line bg-ink-tertiary"
                  title="Открыть файл"
                >
                  {item.thumb_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={mediaUrl(item.thumb_url)}
                      alt=""
                      loading="lazy"
                      decoding="async"
                      referrerPolicy="no-referrer"
                      className="h-full w-full object-cover"
                    />
                  ) : null}
                </a>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`badge ${
                        URGENT.has(item.reason)
                          ? "border-accent-danger text-accent-danger"
                          : "badge-muted"
                      }`}
                    >
                      {item.reason_label ?? item.reason}
                    </span>
                    <span className="font-mono text-[11px] text-text-muted">
                      жалоба #{item.id}
                    </span>
                    <span className="font-mono text-[11px] text-text-muted">
                      {when(item.created_at)}
                    </span>
                    {item.media_visible === false ? (
                      <span className="badge badge-muted">файл скрыт</span>
                    ) : (
                      <span className="badge badge-ok">виден на сайте</span>
                    )}
                  </div>

                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-text-secondary">
                    {item.board_slug ? (
                      <a
                        href={`/board/${item.board_slug}`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-accent-primary hover:underline"
                      >
                        /{item.board_slug}
                      </a>
                    ) : null}
                    {item.thread_id ? (
                      <a
                        href={`/t/${item.thread_id}`}
                        target="_blank"
                        rel="noreferrer"
                        className="font-mono text-[11px] text-text-muted hover:text-accent-primary"
                      >
                        тред #{item.thread_id}
                      </a>
                    ) : null}
                    <span className="max-w-72 truncate" title={item.media_name ?? ""}>
                      {item.media_name ?? `файл #${item.media_id}`}
                    </span>
                    <span className="text-text-muted">от: {item.reporter ?? "неизвестно"}</span>
                  </div>

                  {item.comment ? (
                    <p className="mt-2 whitespace-pre-wrap text-sm text-text-primary">
                      {item.comment}
                    </p>
                  ) : null}
                  {item.resolution_note ? (
                    <p className="mt-2 rounded bg-ink-tertiary/60 px-2 py-1.5 text-xs text-text-secondary">
                      решение: {item.resolution_note}
                    </p>
                  ) : null}

                  {item.status === "open" ? (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <input
                        value={notes[item.id] ?? ""}
                        onChange={(e) =>
                          setNotes((prev) => ({ ...prev, [item.id]: e.target.value }))
                        }
                        placeholder="заметка к решению (необязательно)"
                        className="min-w-44 flex-1 rounded border border-line bg-ink-tertiary px-2 py-1 text-xs text-text-primary outline-none focus:border-accent-primary"
                      />
                      <button
                        type="button"
                        disabled={busy === item.id}
                        onClick={() => void resolve(item, "hide_media")}
                        className="btn-ghost px-2.5 py-1 text-xs"
                      >
                        Скрыть файл
                      </button>
                      <button
                        type="button"
                        disabled={busy === item.id}
                        onClick={() => void resolve(item, "hide_thread")}
                        className="btn-ghost px-2.5 py-1 text-xs"
                      >
                        Скрыть тред
                      </button>
                      <button
                        type="button"
                        disabled={busy === item.id}
                        onClick={() => void resolve(item, "remove_media")}
                        className="rounded border border-accent-danger/40 px-2.5 py-1 text-xs text-accent-danger transition-colors hover:border-accent-danger"
                      >
                        Удалить файл
                      </button>
                      <button
                        type="button"
                        disabled={busy === item.id}
                        onClick={() => void resolve(item, "reject")}
                        className="btn-ghost px-2.5 py-1 text-xs"
                      >
                        Отклонить
                      </button>
                    </div>
                  ) : (
                    <p className="mt-2 font-mono text-[11px] text-text-muted">
                      разобрано: {item.resolved_at ? when(item.resolved_at) : "—"}
                    </p>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Блок-лист запрещённого контента: файл с таким хешем не публикуется */}
      <BlockedHashes />

    </div>
  );
}
