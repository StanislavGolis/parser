"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Switch } from "@/components/Switch";
import { ApiError, apiPatch, apiPost, apiSend } from "@/lib/api";
import { formatNumber, formatUtc } from "@/lib/format";
import type { BoardThread, ParserStatus, ScanStatus, ThreadList } from "@/lib/types";

const PER_PAGE = 50;

/** Чипы фильтра по состоянию треда (ключ → подпись). */
const FILTERS: Array<{ key: string; label: string }> = [
  { key: "all", label: "Все" },
  { key: "active", label: "В работе" },
  { key: "parsing", label: "Парсить" },
  { key: "visible", label: "published" },
  { key: "premium", label: "PREMIUM" },
  { key: "queued", label: "В очереди" },
  { key: "lagging", label: "Недокачано" },
  { key: "stale", label: "Просроченные" },
  { key: "dead", label: "Мёртвые" },
  { key: "off", label: "Без настроек" },
];

/** Человекочитаемые причины очереди докачки (`pending_reason` с бэкенда). */
const PENDING_LABELS: Record<string, string> = {
  "новый": "новый тред",
  "изменения": "новые файлы",
  "просрочен": "плановый догон",
  "не скачивался": "не скачивался",
  "файлы": "сверка файлов",
  "вручную": "вручную",
};

function readToken(): string {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem("admin_token") ?? "";
}

function errText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return err.detail;
  return err instanceof Error ? err.message : "Ошибка";
}

/**
 * Управление тредами доски: флаги «Парсить / published / PREMIUM»
 * и массовые операции над выбранными тредами.
 *
 * Премиум доски закрывает все её треды: переключатели PREMIUM тогда
 * показывают унаследованное значение (сам тред менять не нужно).
 */
export default function AdminBoardThreads({
  slug,
  parserStatus,
  boardPremium = false,
}: {
  slug: string;
  parserStatus?: ParserStatus | null;
  boardPremium?: boolean;
}) {
  const [token] = useState<string>(readToken);
  const [threads, setThreads] = useState<BoardThread[] | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [scan, setScan] = useState<ScanStatus | null>(null);
  const [deep, setDeep] = useState(false);
  const [totals, setTotals] = useState({
    posts_total: 0,
    views_total: 0,
    files_detected_total: 0,
    files_downloaded_total: 0,
  });
  const pollRef = useRef<number | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const [queryInput, setQueryInput] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [counts, setCounts] = useState<Record<string, number> | null>(null);

  const load = useCallback(
    async (p: number) => {
      if (!token) return;
      setBusy(true);
      setError(null);
      try {
        const qs = new URLSearchParams({
          page: String(p),
          per_page: String(PER_PAGE),
          state: filter,
        });
        if (appliedQuery.trim()) qs.set("q", appliedQuery.trim());
        const data = await apiSend<ThreadList>(
          `/api/v1/admin/boards/${encodeURIComponent(slug)}/threads?${qs.toString()}`,
          { token },
        );
        setThreads((prev) => {
          if (p === 1) return data.items;
          const seen = new Set((prev ?? []).map((t) => t.thread_id));
          return [...(prev ?? []), ...data.items.filter((t) => !seen.has(t.thread_id))];
        });
        setPage(data.page);
        setTotal(data.total);
        setCounts(data.counts ?? null);
        setTotals({
          posts_total: data.posts_total ?? 0,
          views_total: data.views_total ?? 0,
          files_detected_total: data.files_detected_total ?? 0,
          files_downloaded_total: data.files_downloaded_total ?? 0,
        });
      } catch (err) {
        setError(errText(err));
      } finally {
        setBusy(false);
      }
    },
    [slug, token, filter, appliedQuery],
  );

  useEffect(() => {
    if (token) void load(1);
  }, [token, load]);

  // Останавливаем поллинг прогресса при размонтировании
  useEffect(() => () => {
    if (pollRef.current) window.clearTimeout(pollRef.current);
  }, []);

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

  /** Поллинг прогресса сканирования каталога. */
  const pollScan = useCallback(async () => {
    try {
      const st = await apiSend<ScanStatus>(
        `/api/v1/admin/boards/${encodeURIComponent(slug)}/scan/status`,
        { token },
      );
      setScan(st);
      if (st.status === "running") {
        pollRef.current = window.setTimeout(() => void pollScan(), 700);
      } else if (st.status === "done") {
        await load(1);
        pollRef.current = window.setTimeout(() => setScan(null), 2500);
      }
    } catch (err) {
      setError(errText(err));
      setScan(null);
    }
  }, [slug, token, load]);

  /** Сканирование каталога доски: запуск + поллинг прогресса. */
  const startScan = useCallback(async () => {
    setError(null);
    try {
      const st = await apiPost<ScanStatus>(
        `/api/v1/admin/boards/${encodeURIComponent(slug)}/scan?deep=${deep ? "true" : "false"}`,
        undefined,
        token,
      );
      setScan(st);
      if (st.status === "running") {
        pollRef.current = window.setTimeout(() => void pollScan(), 400);
      }
    } catch (err) {
      setError(errText(err));
    }
  }, [slug, token, pollScan, deep]);

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

      {/* Сканирование каталога доски (discovery + опционально подсчёт файлов) */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-text-muted">
          {threads
            ? `тредов: ${formatNumber(total)} · постов: ${formatNumber(totals.posts_total)} · просмотров: ${formatNumber(totals.views_total)} · файлов на форуме: ${formatNumber(totals.files_detected_total)} · скачано: ${formatNumber(totals.files_downloaded_total)}${
                (counts?.dead ?? 0) > 0 ? ` · мёртвых: ${formatNumber(counts?.dead ?? 0)}` : ""
              }${(counts?.stale ?? 0) > 0 ? ` · просрочено: ${formatNumber(counts?.stale ?? 0)}` : ""}${
                (counts?.pending ?? 0) > 0 ? ` · в очереди: ${formatNumber(counts?.pending ?? 0)}` : ""
              }${(counts?.lagging ?? 0) > 0 ? ` · недокачано: ${formatNumber(counts?.lagging ?? 0)}` : ""}`
            : "загрузка…"}
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <label
            className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-text-secondary"
            title="Прочитать res/{id}.json каждого треда и посчитать файлы (медленнее, но покажет «файлов на форуме» до парсинга)"
          >
            <input type="checkbox" checked={deep} onChange={(e) => setDeep(e.target.checked)} />
            считать файлы
          </label>
          <button
            type="button"
            disabled={scan?.status === "running" || busy}
            onClick={() => void startScan()}
            className="btn-ghost px-2.5 py-1.5 text-xs"
            title="Сканировать каталог доски и загрузить список тредов"
          >
            {scan?.status === "running" ? "Сканируем…" : "Сканировать треды"}
          </button>
        </div>
      </div>

      {scan && scan.status !== "idle" ? (
        <div className="mb-3 rounded border border-line bg-ink-secondary px-3 py-2">
          <div className="flex items-center justify-between text-xs text-text-secondary">
            <span>
              {scan.status === "running"
                ? scan.phase === "files"
                  ? "Считаем файлы в тредах…"
                  : "Сканируем каталог доски…"
                : scan.status === "done"
                  ? `Готово: тредов ${formatNumber(scan.total)}${
                      scan.phase === "files"
                        ? ` · файлов на форуме ${formatNumber(scan.files_total ?? 0)}`
                        : ""
                    }`
                  : `Ошибка: ${scan.error ?? "не удалось"}`}
            </span>
            <span className="tabular-nums">
              {formatNumber(scan.done)}/{formatNumber(scan.total || 0)}
            </span>
          </div>
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded bg-ink-tertiary">
            <div
              className={`h-full transition-all ${
                scan.status === "error" ? "bg-accent-danger" : "bg-accent-primary"
              }`}
              style={{
                width: `${
                  scan.total > 0
                    ? Math.min(100, Math.round((scan.done / scan.total) * 100))
                    : scan.status === "running"
                      ? 15
                      : scan.status === "done"
                        ? 100
                        : 0
                }%`,
              }}
            />
          </div>
        </div>
      ) : null}
      {/* Фильтры и поиск по тредам */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1">
          {FILTERS.map((f) => {
            const active = filter === f.key;
            const cnt = counts?.[f.key];
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={`rounded border px-2.5 py-1 text-xs transition-colors ${
                  active
                    ? "border-accent-primary/50 bg-accent-primary/15 text-accent-primary"
                    : "border-line bg-ink-tertiary text-text-secondary hover:text-text-primary"
                }`}
              >
                {f.label}
                {cnt !== undefined ? (
                  <span className="ml-1 text-text-muted">{formatNumber(cnt)}</span>
                ) : null}
              </button>
            );
          })}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setAppliedQuery(queryInput);
          }}
          className="ml-auto flex items-center gap-2"
        >
          <input
            type="text"
            value={queryInput}
            onChange={(e) => setQueryInput(e.target.value)}
            placeholder="Поиск по теме / № треда"
            className="w-56 rounded border border-line bg-ink-secondary px-2.5 py-1.5 text-xs text-text-primary outline-none placeholder:text-text-muted focus:border-accent-primary"
          />
          <button type="submit" className="btn-ghost px-2.5 py-1.5 text-xs">
            Найти
          </button>
          {appliedQuery ? (
            <button
              type="button"
              onClick={() => {
                setQueryInput("");
                setAppliedQuery("");
              }}
              className="btn-ghost px-2.5 py-1.5 text-xs"
            >
              Сброс
            </button>
          ) : null}
        </form>
      </div>

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
          <span className="mx-1 h-4 w-px bg-line" />
          <button type="button" disabled={disabled} onClick={() => void bulk({ is_premium: true })} className="btn-ghost px-2.5 py-1 text-xs">
            PREMIUM: вкл
          </button>
          <button type="button" disabled={disabled} onClick={() => void bulk({ is_premium: false })} className="btn-ghost px-2.5 py-1 text-xs">
            PREMIUM: выкл
          </button>
          <span className="mx-1 h-4 w-px bg-line" />
          <button
            type="button"
            disabled={disabled}
            title="Вернуть выбранные треды в работу и в публичные списки (промахи каталога сбрасываются)"
            onClick={() => void bulk({ restore: true })}
            className="btn-ghost px-2.5 py-1 text-xs"
          >
            Вернуть в обход
          </button>
          <button
            type="button"
            disabled={disabled}
            title="Поставить выбранные треды в очередь докачки (работает при включённом «Парсить»)"
            onClick={() => void bulk({ requeue: true })}
            className="btn-ghost px-2.5 py-1 text-xs"
          >
            В очередь
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
            {threads.map((t, idx) => {
              const isWork = t.parse_enabled || t.is_visible || t.is_premium;
              const prev = idx > 0 ? threads[idx - 1] : null;
              const prevWork = prev ? prev.parse_enabled || prev.is_visible || prev.is_premium : null;
              const showHeader = filter === "all" && (idx === 0 || isWork !== prevWork);
              return (
                <Fragment key={t.thread_id}>
                  {showHeader ? (
                    <div className="mt-1 font-mono text-[11px] uppercase tracking-wider text-text-muted">
                      {isWork
                        ? `в работе (${formatNumber(counts?.active ?? 0)})`
                        : `без настроек (${formatNumber(counts?.off ?? 0)})`}
                    </div>
                  ) : null}
                  <div className="rounded border border-line bg-ink-secondary px-4 py-3">
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
                    {t.is_premium || boardPremium ? (
                      <span className="badge badge-warn">premium</span>
                    ) : null}
                    <span className="font-mono text-xs text-text-muted">№{t.thread_id}</span>
                    {t.pending_scan ? (
                      <span
                        className="badge badge-ok"
                        title="Тред в очереди на докачку (фаза B): свежие файлы идут раньше планового догона"
                      >
                        очередь: {PENDING_LABELS[t.pending_reason ?? ""] ?? t.pending_reason ?? "скан"}
                      </span>
                    ) : null}
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
                      label={t.is_visible ? "published" : "unpublished"}
                      title="Показывать тред на сайте (published/unpublished)"
                      onChange={() => void patchThread(t.thread_id, { is_visible: !t.is_visible })}
                    />
                    <Switch
                      checked={boardPremium || t.is_premium}
                      disabled={boardPremium}
                      label={boardPremium || t.is_premium ? "PREMIUM" : "FREE"}
                      title={
                        boardPremium
                          ? "Премиум включён на уровне доски — действует для всех тредов"
                          : "Премиум-доступ к файлам этого треда"
                      }
                      onChange={() => void patchThread(t.thread_id, { is_premium: !t.is_premium })}
                    />
                    {boardPremium ? (
                      <span className="font-mono text-[10px] text-accent-warning">
                        унаследовано от доски
                      </span>
                    ) : null}
                  </div>
                </div>

                <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary">
                  <span>
                    файлов: <b className="text-text-primary">{formatNumber(t.files_detected)}</b>
                  </span>
                  <span>скачано: {formatNumber(t.media_total)}</span>
                  <span>в хранилище: {formatNumber(t.media_in_s3)}</span>
                  <span>видимых: {formatNumber(t.media_visible)}</span>
                  <span className="text-text-muted">постов: {formatNumber(t.posts_count)}</span>
                  <span className="text-text-muted">просмотров: {formatNumber(t.views_count)}</span>
                </div>

                {!t.is_active ? (
                  <div className="mt-2 flex flex-wrap items-center gap-2 rounded border border-accent-danger/40 bg-accent-danger/10 px-2 py-1.5 text-[11px] text-accent-danger">
                    <span className="font-mono uppercase tracking-wider">нет в каталоге</span>
                    <span>
                      {t.missing_since ? `с ${formatUtc(t.missing_since)}` : "дата неизвестна"}
                      {t.misses > 0 ? ` · промахов: ${formatNumber(t.misses)}` : ""}
                    </span>
                    <button
                      type="button"
                      disabled={busyKey === `t${t.thread_id}`}
                      title="Вернуть тред в работу и в публичные списки (промахи каталога сбрасываются)"
                      onClick={() => void patchThread(t.thread_id, { restore: true })}
                      className="rounded border border-accent-danger/50 px-2 py-0.5 transition-colors hover:bg-accent-danger/20 disabled:opacity-50"
                    >
                      вернуть в обход
                    </button>
                  </div>
                ) : t.is_stale ? (
                  <div className="mt-2 rounded border border-accent-warning/40 bg-accent-warning/10 px-2 py-1.5 text-[11px] text-accent-warning">
                    просрочен: парсинг включён, но тред не сканировался
                    {t.last_scanned_at ? ` с ${formatUtc(t.last_scanned_at)}` : " ни разу"}
                    {t.last_scan_attempt_at ? ` · попытка: ${formatUtc(t.last_scan_attempt_at)}` : ""}
                  </div>
                ) : null}

                {parserStatus?.current_board === slug &&
                parserStatus.progress?.thread_id === t.thread_id ? (
                  <div className="mt-2">
                    <div className="h-1 w-full overflow-hidden rounded bg-ink-tertiary">
                      <div
                        className={`h-full transition-all ${
                          (parserStatus.stall_seconds ?? 0) > 60
                            ? "bg-accent-danger"
                            : "bg-accent-primary"
                        }`}
                        style={{
                          width: `${
                            (parserStatus.progress?.files_total ?? 0) > 0
                              ? Math.min(
                                  100,
                                  Math.round(
                                    ((parserStatus.progress?.files_done ?? 0) /
                                      (parserStatus.progress?.files_total ?? 1)) *
                                      100,
                                  ),
                                )
                              : 10
                          }%`,
                        }}
                      />
                    </div>
                    <div className="mt-1 font-mono text-[10px] text-text-muted">
                      парсим: {formatNumber(parserStatus.progress?.files_done ?? 0)}/
                      {formatNumber(parserStatus.progress?.files_total ?? 0)} файлов
                      {parserStatus.stall_seconds != null
                        ? ` · ${parserStatus.stall_seconds} с назад`
                        : ""}
                    </div>
                  </div>
                ) : null}

                {t.is_premium ? (
                  <div className="mt-2 border-t border-line pt-2 text-[11px] text-accent-warning">
                    Премиум-тред: превью размыты, полные файлы — по подписке.
                  </div>
                ) : null}
                  </div>
                </Fragment>
              );
            })}
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
