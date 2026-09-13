"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiPatch, apiSend } from "@/lib/api";
import { useAdminToken } from "@/lib/adminAuth";
import { formatNumber, parseUtc } from "@/lib/format";
import type { FeedbackItem, FeedbackList } from "@/lib/types";

const POLL_MS = 15000;

const STATUSES: Array<{ value: string; label: string }> = [
  { value: "all", label: "Все" },
  { value: "new", label: "Новые" },
  { value: "in_progress", label: "В работе" },
  { value: "answered", label: "Отвечено" },
  { value: "closed", label: "Закрыто" },
];

function errText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return err.detail;
  return err instanceof Error ? err.message : "Ошибка";
}

function when(iso: string): string {
  const time = parseUtc(iso);
  return Number.isFinite(time) ? new Date(time).toLocaleString("ru-RU") : "—";
}

/** Приёмная обратной связи: заявки, статусы и заметка-ответ администратора. */
export default function FeedbackPanel() {
  const { token, logout } = useAdminToken();
  const [data, setData] = useState<FeedbackList | null>(null);
  const [status, setStatus] = useState("all");
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});

  const load = useCallback(
    async (t: string, filter: string, q: string) => {
      try {
        const qs = new URLSearchParams({ status: filter, per_page: "50" });
        if (q.trim()) qs.set("q", q.trim());
        setData(
          await apiSend<FeedbackList>(`/api/v1/admin/feedback?${qs.toString()}`, { token: t }),
        );
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
    void load(token, status, applied);
    const id = window.setInterval(() => void load(token, status, applied), POLL_MS);
    return () => window.clearInterval(id);
  }, [token, status, applied, load]);

  async function patch(id: number, body: Record<string, unknown>) {
    if (!token) return;
    setBusy(id);
    setError(null);
    try {
      await apiPatch(`/api/v1/admin/feedback/${id}`, body, token);
      await load(token, status, applied);
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
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setApplied(query);
          }}
          className="ml-auto flex items-center gap-2"
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="поиск: текст, email, адрес"
            className="w-64 rounded border border-line bg-ink-secondary px-3 py-1.5 text-sm text-text-primary outline-none focus:border-accent-primary"
          />
          <button type="submit" className="btn-ghost px-3 py-1.5 text-xs">
            Найти
          </button>
        </form>
      </div>

      {error ? (
        <p className="mb-4 rounded border border-accent-danger/30 bg-red-500/10 px-3 py-2 text-sm text-accent-danger">
          {error}
        </p>
      ) : null}

      {data === null ? (
        <p className="py-10 text-center text-sm text-text-secondary">Загружаем обращения…</p>
      ) : data.items.length === 0 ? (
        <p className="py-10 text-center text-sm text-text-secondary">Обращений нет.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {data.items.map((item: FeedbackItem) => (
            <div key={item.id} className="rounded border border-line bg-ink-secondary px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-text-muted">#{item.id}</span>
                <span className="rounded bg-ink-tertiary px-1.5 py-0.5 text-[10px] text-text-secondary">
                  {item.topic_label ?? item.topic}
                </span>
                <span className="font-mono text-[10px] text-text-muted">{when(item.created_at)}</span>
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] ${
                    item.status === "new"
                      ? "bg-accent-primary/10 text-accent-primary"
                      : item.status === "answered"
                        ? "bg-accent-secondary/10 text-accent-secondary"
                        : "bg-ink-tertiary text-text-secondary"
                  }`}
                >
                  {item.status}
                </span>
                {item.email ? (
                  <a
                    href={`mailto:${item.email}`}
                    className="font-mono text-[10px] text-accent-primary hover:underline"
                  >
                    {item.email}
                  </a>
                ) : (
                  <span className="font-mono text-[10px] text-text-muted">без контакта</span>
                )}
                {item.user_id ? (
                  <span className="font-mono text-[10px] text-text-muted">
                    аккаунт #{item.user_id}
                  </span>
                ) : null}
                {item.page_url ? (
                  <a
                    href={item.page_url}
                    target="_blank"
                    rel="noreferrer"
                    className="max-w-64 truncate font-mono text-[10px] text-text-muted hover:text-accent-primary"
                  >
                    {item.page_url}
                  </a>
                ) : null}
              </div>

              <p className="mt-2 whitespace-pre-wrap text-sm text-text-primary">{item.message}</p>

              {item.admin_note ? (
                <p className="mt-2 rounded bg-ink-tertiary/60 px-2 py-1.5 text-xs text-text-secondary">
                  заметка: {item.admin_note}
                </p>
              ) : null}

              <div className="mt-2 flex flex-wrap items-center gap-2">
                <input
                  value={notes[item.id] ?? ""}
                  onChange={(e) => setNotes((prev) => ({ ...prev, [item.id]: e.target.value }))}
                  placeholder="заметка / ответ (виден только админам)"
                  className="min-w-48 flex-1 rounded border border-line bg-ink-tertiary px-2 py-1 text-xs text-text-primary outline-none focus:border-accent-primary"
                />
                <button
                  type="button"
                  disabled={busy === item.id || !(notes[item.id] ?? "").trim()}
                  onClick={() => void patch(item.id, { admin_note: notes[item.id] ?? "" })}
                  className="btn-ghost px-2.5 py-1 text-xs"
                >
                  Сохранить заметку
                </button>
                {item.status !== "in_progress" ? (
                  <button
                    type="button"
                    disabled={busy === item.id}
                    onClick={() => void patch(item.id, { status: "in_progress" })}
                    className="btn-ghost px-2.5 py-1 text-xs"
                  >
                    В работу
                  </button>
                ) : null}
                {item.status !== "answered" ? (
                  <button
                    type="button"
                    disabled={busy === item.id}
                    onClick={() => void patch(item.id, { status: "answered" })}
                    className="btn-ghost px-2.5 py-1 text-xs"
                  >
                    Отвечено
                  </button>
                ) : null}
                {item.status !== "closed" ? (
                  <button
                    type="button"
                    disabled={busy === item.id}
                    onClick={() => void patch(item.id, { status: "closed" })}
                    className="btn-ghost px-2.5 py-1 text-xs"
                  >
                    Закрыть
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

