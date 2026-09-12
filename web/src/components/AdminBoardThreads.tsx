"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Switch } from "@/components/Switch";
import { ApiError, apiPatch, apiPost, apiSend } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import type { BoardThread, ThreadList } from "@/lib/types";

const PER_PAGE = 50;

function readToken(): string {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem("admin_token") ?? "";
}

function errText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return err.detail;
  return err instanceof Error ? err.message : "Ошибка";
}

/**
 * Управление тредами доски: флаги «Парсить / На сайте / По коду», код доступа
 * и массовые операции над выбранными тредами.
 */
export default function AdminBoardThreads({ slug }: { slug: string }) {
  const [token] = useState<string>(readToken);
  const [threads, setThreads] = useState<BoardThread[] | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [codes, setCodes] = useState<Record<number, string>>({});

  const load = useCallback(
    async (p: number) => {
      if (!token) return;
      setBusy(true);
      setError(null);
      try {
        const data = await apiSend<ThreadList>(
          `/api/v1/admin/boards/${encodeURIComponent(slug)}/threads?page=${p}&per_page=${PER_PAGE}`,
          { token },
        );
        setThreads((prev) => {
          if (p === 1) return data.items;
          const seen = new Set((prev ?? []).map((t) => t.thread_id));
          return [...(prev ?? []), ...data.items.filter((t) => !seen.has(t.thread_id))];
        });
        setPage(data.page);
        setTotal(data.total);
      } catch (err) {
        setError(errText(err));
      } finally {
        setBusy(false);
      }
    },
    [slug, token],
  );

  useEffect(() => {
    if (token) void load(1);
  }, [token, load]);

  const patchThread = useCallback(
    async (threadId: number, body: Record<string, unknown>) => {
      setBusyKey(`t${threadId}`);
      setError(null);
      try {
        const updated = await apiPatch<BoardThread>(
          `/api/v1/admin/boards/${encodeURIComponent(slug)}/threads/${threadId}`,
          body,
          token,
        );
        setThreads((prev) => (prev ?? []).map((t) => (t.thread_id === threadId ? updated : t)));
      } catch (err) {
        setError(errText(err));
      } finally {
        setBusyKey(null);
      }
    },
    [slug, token],
  );

  const bulk = useCallback(
    async (body: Record<string, unknown>) => {
      if (selected.size === 0) return;
      setBusy(true);
      setError(null);
      try {
        await apiPost(
          `/api/v1/admin/boards/${encodeURIComponent(slug)}/threads/bulk`,
          { thread_ids: [...selected], ...body },
          token,
        );
        setSelected(new Set());
        await load(1);
      } catch (err) {
        setError(errText(err));
      } finally {
        setBusy(false);
      }
    },
    [selected, slug, token, load],
  );

  const allSelected = useMemo(
    () => (threads?.length ?? 0) > 0 && selected.size === (threads?.length ?? 0),
    [threads, selected],
  );

  function toggleSelect(threadId: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(threadId)) next.delete(threadId);
      else next.add(threadId);
      return next;
    });
  }

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set((threads ?? []).map((t) => t.thread_id)));
  }

  if (!token) {
    return <p className="py-10 text-center text-sm text-text-secondary">Требуется вход в админ-панель.</p>;
  }

  const disabled = busy || selected.size === 0;

  return (
    <div>
      {error ? <p className="mb-4 text-sm text-accent-danger">{error}</p> : null}
      {threads && threads.length > 0 ? (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded border border-line bg-ink-secondary px-3 py-2 text-xs">
          <label className="inline-flex cursor-pointer items-center gap-2 text-text-secondary">
            <input type="checkbox" checked={allSelected} onChange={toggleAll} />
            выбрать все
          </label>
          <span className="text-text-muted">выбрано: {formatNumber(selected.size)}</span>
          <span className="mx-1 h-4 w-px bg-line" />
          <button type="button" disabled={disabled} onClick={() => void bulk({ parse_enabled: true })} className="btn-ghost px-2.5 py-1 text-xs">
            Парсить: вкл
          </button>
          <button type="button" disabled={disabled} onClick={() => void bulk({ parse_enabled: false })} className="btn-ghost px-2.5 py-1 text-xs">
            Парсить: выкл
          </button>
          <button type="button" disabled={disabled} onClick={() => void bulk({ is_visible: true })} className="btn-ghost px-2.5 py-1 text-xs">
            Показать
          </button>
          <button type="button" disabled={disabled} onClick={() => void bulk({ is_visible: false })} className="btn-ghost px-2.5 py-1 text-xs">
            Скрыть
          </button>
        </div>
      ) : null}
      {threads === null ? (
        <p className="py-8 text-center text-sm text-text-secondary">Загружаем треды…</p>
      ) : threads.length === 0 ? (
        <p className="py-8 text-center text-sm text-text-secondary">Треды ещё не просканированы.</p>
      ) : (
        <>
          <div className="flex flex-col gap-2">
            {threads.map((t) => (
              <div key={t.thread_id} className="rounded border border-line bg-ink-secondary px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex min-w-0 flex-1 items-center gap-2">
                    <input
                      type="checkbox"
                      checked={selected.has(t.thread_id)}
                      onChange={() => toggleSelect(t.thread_id)}
                    />
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-text-primary">
                      {t.subject?.trim() || `Тред №${t.thread_id}`}
                    </span>
                    <span className="font-mono text-xs text-text-muted">№{t.thread_id}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Switch
                      checked={t.parse_enabled}
                      label="Парсить"
                      title="Скачивать файлы этого треда"
                      onChange={() => void patchThread(t.thread_id, { parse_enabled: !t.parse_enabled })}
                    />
                    <Switch
                      checked={t.is_visible}
                      label="На сайте"
                      title="Показывать тред публично"
                      onChange={() => void patchThread(t.thread_id, { is_visible: !t.is_visible })}
                    />
                    <Switch
                      checked={t.is_private}
                      label="По коду"
                      title="Контент треда доступен только по коду"
                      onChange={() => void patchThread(t.thread_id, { is_private: !t.is_private })}
                    />
                  </div>
                </div>

                <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary">
                  <span>каталог: {formatNumber(t.files_count)}</span>
                  <span>в БД: {formatNumber(t.media_total)}</span>
                  <span>в S3: {formatNumber(t.media_in_s3)}</span>
                  <span>видимых: {formatNumber(t.media_visible)}</span>
                  <span className="text-text-muted">постов: {formatNumber(t.posts_count)}</span>
                </div>

                {t.is_private ? (
                  <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-line pt-2">
                    <span className={`text-xs ${t.has_access_code ? "text-accent-secondary" : "text-text-muted"}`}>
                      {t.has_access_code ? "код задан" : "код не задан"}
                    </span>
                    <input
                      type="text"
                      value={codes[t.thread_id] ?? ""}
                      onChange={(e) => setCodes((prev) => ({ ...prev, [t.thread_id]: e.target.value }))}
                      placeholder="Код доступа треда"
                      className="w-48 rounded border border-line bg-ink-secondary px-2.5 py-1.5 text-xs text-text-primary outline-none placeholder:text-text-muted focus:border-accent-primary"
                    />
                    <button
                      type="button"
                      disabled={busyKey === `t${t.thread_id}` || !(codes[t.thread_id] ?? "").trim()}
                      onClick={() => void patchThread(t.thread_id, { access_code: codes[t.thread_id] })}
                      className="btn-ghost px-2.5 py-1.5 text-xs"
                    >
                      Задать код
                    </button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>

          {threads.length < total ? (
            <div className="mt-4 flex justify-center">
              <button type="button" disabled={busy} onClick={() => void load(page + 1)} className="btn-ghost">
                {busy ? "Загружаем…" : `Показать ещё (${formatNumber(threads.length)} из ${formatNumber(total)})`}
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
