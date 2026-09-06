"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiSend } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import type { BoardThread, ThreadList } from "@/lib/types";

const PER_PAGE = 50;

export default function AdminBoardThreads({ slug }: { slug: string }) {
  const [token, setToken] = useState<string>(() =>
    typeof window === "undefined" ? "" : window.sessionStorage.getItem("admin_token") ?? "",
  );
  const [threads, setThreads] = useState<BoardThread[] | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
        const msg = err instanceof ApiError ? (err.detail ?? err.message) : "Ошибка загрузки";
        setError(msg);
      } finally {
        setBusy(false);
      }
    },
    [slug, token],
  );

  useEffect(() => {
    if (token) void load(1);
  }, [token, load]);

  if (!token) {
    return <p className="py-10 text-center text-sm text-text-secondary">Требуется вход в админ-панель.</p>;
  }

  return (
    <div>
      {error ? <p className="mb-4 text-sm text-accent-danger">{error}</p> : null}
      {threads === null ? (
        <p className="py-8 text-center text-sm text-text-secondary">Загружаем треды…</p>
      ) : threads.length === 0 ? (
        <p className="py-8 text-center text-sm text-text-secondary">Треды ещё не просканированы.</p>
      ) : (
        <>
          <div className="flex flex-col gap-2">
            {threads.map((t) => (
              <div
                key={t.thread_id}
                className="rounded border border-line bg-ink-secondary px-4 py-3"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-text-primary">
                    {t.subject?.trim() || `Тред №${t.thread_id}`}
                  </span>
                  <span className="font-mono text-xs text-text-muted">№{t.thread_id}</span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary">
                  <span>каталог: {formatNumber(t.files_count)}</span>
                  <span>в БД: {formatNumber(t.media_total)}</span>
                  <span>в B2: {formatNumber(t.media_in_b2)}</span>
                  <span>скачано: {formatNumber(t.media_downloaded)}</span>
                  <span>пропущено: {formatNumber(t.media_missing)}</span>
                  <span>видимых: {formatNumber(t.media_visible)}</span>
                  <span className="text-text-muted">постов: {formatNumber(t.posts_count)}</span>
                </div>
              </div>
            ))}
          </div>

          {threads.length < total ? (
            <div className="mt-4 flex justify-center">
              <button
                type="button"
                disabled={busy}
                onClick={() => void load(page + 1)}
                className="btn-ghost"
              >
                {busy ? "Загружаем…" : `Показать ещё (${formatNumber(threads.length)} из ${formatNumber(total)})`}
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
