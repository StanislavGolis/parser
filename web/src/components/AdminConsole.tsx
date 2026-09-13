"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import Link from "next/link";

import { PlusIcon, SpinnerIcon } from "@/components/icons";
import { BoardsTable, CatalogTab } from "@/components/AdminViews";
import { ApiError, apiDelete, apiPatch, apiPost, apiSend } from "@/lib/api";
import { useAdminToken } from "@/lib/adminAuth";
import { formatBytes, formatNumber, parseUtc } from "@/lib/format";
import type {
  AdminBoard,
  AdminOverview,
  BackfillStatus,
  SourceBoard,
  MediaCacheStats,
  ParserStatus,
  SourceInfo,
  SourceStatus,
  SystemTotals,
} from "@/lib/types";

const POLL_MS = 2000; // сводка (агрегаты по доскам) — раз в 2 c
const PARSER_POLL_MS = 1000; // статус парсера (лёгкий запрос) — раз в 1 c
const SOURCES_POLL_MS = 5000; // реестр источников — раз в 5 c
const CACHE_POLL_MS = 10000; // состояние кэша медиа (обход каталога) — раз в 10 c

type Tab = "boards" | "catalog";

function errText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return err.detail;
  return err instanceof Error ? err.message : "Ошибка";
}

export default function AdminConsole() {
  const { token, logout } = useAdminToken();
  const [tab, setTab] = useState<Tab>("boards");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [catalog, setCatalog] = useState<SourceBoard[] | null>(null);
  const [catalogQuery, setCatalogQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [newSlug, setNewSlug] = useState("");
  const [creating, setCreating] = useState(false);
  const [addError, setAddError] = useState<{ message: string; canForce: boolean; slug: string } | null>(
    null,
  );
  const [catalogError, setCatalogError] = useState<Record<string, { message: string; canForce: boolean }>>(
    {},
  );
  const [backfill, setBackfill] = useState<BackfillStatus | null>(null);
  const backfillPollRef = useRef<number | null>(null);
  const [parserStatus, setParserStatus] = useState<ParserStatus | null>(null);
  // Реестр источников: из него строятся вкладки «Контента» и берётся статус
  // прогона активного источника (у каждого источника свой флаг и прогресс)
  const [sources, setSources] = useState<SourceInfo[] | null>(null);
  const [sourceCode, setSourceCode] = useState<string | null>(null);
  const [cacheStats, setCacheStats] = useState<MediaCacheStats | null>(null);
  const [cacheBusy, setCacheBusy] = useState(false);

  const loadOverview = useCallback(
    async (t: string) => {
      try {
        const data = await apiSend<AdminOverview>("/api/v1/admin/overview", { token: t });
        setOverview(data);
        setGlobalError(null);
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          // Токен неверен или отозван: гейт в layout вернёт форму входа.
          logout();
        } else {
          setGlobalError(errText(err));
        }
      }
    },
    [logout],
  );

  // Первичная загрузка + polling: статистика обновляется без перезагрузки.
  useEffect(() => {
    if (!token) return;
    setLoading(true);
    void loadOverview(token).finally(() => setLoading(false));
    const id = window.setInterval(() => {
      void loadOverview(token);
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [token, loadOverview]);

  const loadParserStatus = useCallback(
    async (t: string) => {
      if (!sourceCode) {
        setParserStatus(null);
        return;
      }
      try {
        const data = await apiSend<SourceStatus>(
          `/api/v1/admin/sources/${encodeURIComponent(sourceCode)}/status`,
          { token: t },
        );
        const updatedAt = data.progress?.updated_at;
        // Время из API — UTC (иногда без суффикса Z): parseUtc не даёт сдвинуть
        // «простой» на часовой пояс браузера
        const ts = typeof updatedAt === "string" ? parseUtc(updatedAt) : NaN;
        setParserStatus({
          up: data.up,
          enabled: data.enabled,
          alive: data.alive,
          current_board: data.current,
          progress: data.progress,
          stall_seconds: Number.isFinite(ts)
            ? Math.max(0, Math.round((Date.now() - ts) / 1000))
            : null,
        });
      } catch {
        /* тихо игнорируем — следующий тик повторит */
      }
    },
    [sourceCode],
  );

  // Реестр источников (вкладки «Контента»): опрашиваем редко, данные лёгкие
  const loadSources = useCallback(
    async (t: string) => {
      try {
        const data = await apiSend<{ items: SourceInfo[] }>("/api/v1/admin/sources", { token: t });
        setSources(data.items);
        setSourceCode((prev) => prev ?? data.items[0]?.code ?? null);
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) logout();
      }
    },
    [logout],
  );

  useEffect(() => {
    if (!token) return;
    void loadSources(token);
    const id = window.setInterval(() => void loadSources(token), SOURCES_POLL_MS);
    return () => window.clearInterval(id);
  }, [token, loadSources]);

  const activeSource = useMemo(
    () => (sources ?? []).find((s) => s.code === sourceCode) ?? null,
    [sources, sourceCode],
  );
  // Доски активного источника: контент источников не смешивается во вкладках
  const visibleBoards = useMemo(() => {
    const boards = overview?.boards ?? null;
    if (!boards || !activeSource) return boards;
    return boards.filter((b) => b.source_id === activeSource.id);
  }, [overview?.boards, activeSource]);

  // Лёгкий статус парсера — раз в секунду (живость + прогресс текущего треда)
  useEffect(() => {
    if (!token) return;
    void loadParserStatus(token);
    const id = window.setInterval(() => void loadParserStatus(token), PARSER_POLL_MS);
    return () => window.clearInterval(id);
  }, [token, loadParserStatus]);

  /** Разделы активного источника: что он предлагает завести (аналог «досок форума»). */
  const loadCatalog = useCallback(
    async (code: string) => {
      if (!token) return;
      setLoading(true);
      setGlobalError(null);
      try {
        const data = await apiSend<SourceBoard[]>(
          `/api/v1/admin/sources/${encodeURIComponent(code)}/catalog`,
          { token },
        );
        setCatalog(data);
      } catch (err) {
        setGlobalError(errText(err));
        setCatalog(null);
      } finally {
        setLoading(false);
      }
    },
    [token],
  );

  // Список разделов читаем при открытии вкладки и при смене источника (категории
  // и доски меняются редко, поэтому без поллинга)
  useEffect(() => {
    if (!token || tab !== "catalog" || !sourceCode) return;
    void loadCatalog(sourceCode);
  }, [token, tab, sourceCode, loadCatalog]);

  // Останавливаем поллинг бэкфилла при размонтировании
  useEffect(() => () => {
    if (backfillPollRef.current) window.clearTimeout(backfillPollRef.current);
  }, []);

  function replaceBoard(updated: AdminBoard) {
    setOverview((prev) =>
      prev ? { ...prev, boards: prev.boards.map((b) => (b.slug === updated.slug ? updated : b)) } : prev,
    );
  }

  async function patch(slug: string, body: Record<string, unknown>) {
    if (!token) return;
    setBusyKey(slug);
    setRowError((prev) => ({ ...prev, [slug]: "" }));
    try {
      const updated = await apiPatch<AdminBoard>(
        `/api/v1/admin/boards/${encodeURIComponent(slug)}`,
        body,
        token,
      );
      replaceBoard(updated);
    } catch (err) {
      setRowError((prev) => ({ ...prev, [slug]: errText(err) }));
    } finally {
      setBusyKey(null);
    }
  }

  /** Перемещение доски в очереди парсинга (▲/▼). */
  async function moveBoard(slug: string, dir: -1 | 1) {
    if (!token || !overview) return;
    const boards = overview.boards;
    const idx = boards.findIndex((b) => b.slug === slug);
    const jdx = idx + dir;
    if (idx < 0 || jdx < 0 || jdx >= boards.length) return;
    const next = [...boards];
    [next[idx], next[jdx]] = [next[jdx], next[idx]];
    setOverview({ ...overview, boards: next });
    try {
      await apiPost("/api/v1/admin/boards/reorder", { slugs: next.map((b) => b.slug) }, token);
    } catch (err) {
      setGlobalError(errText(err));
      void loadOverview(token);
    }
  }

  async function removeBoard(slug: string) {
    if (!token) return;
    setBusyKey(slug);
    try {
      await apiDelete<{ deleted_boards: number }>(`/api/v1/admin/boards/${encodeURIComponent(slug)}`, token);
      setOverview((prev) =>
        prev ? { ...prev, boards: prev.boards.filter((b) => b.slug !== slug) } : prev,
      );
    } catch (err) {
      setGlobalError(errText(err));
    } finally {
      setBusyKey(null);
    }
  }

  async function resetAll() {
    if (!token) return;
    if (!window.confirm("Полный сброс: удалить ВСЕ разделы и ВСЕ файлы из хранилища (S3)?")) return;
    if (!window.confirm("Точно? Действие необратимо: БД и бакет будут очищены.")) return;
    setGlobalError(null);
    try {
      await apiDelete("/api/v1/admin/reset", token);
      await loadOverview(token);
    } catch (err) {
      setGlobalError(errText(err));
    }
  }

  async function startParser() {
    if (!token || !sourceCode) return;
    try {
      await apiPost(`/api/v1/admin/sources/${encodeURIComponent(sourceCode)}/start`, undefined, token);
      setGlobalError(null);
      await loadOverview(token);
    } catch (err) {
      setGlobalError(errText(err));
    }
  }

  async function stopParser() {
    if (!token || !sourceCode) return;
    try {
      await apiPost(`/api/v1/admin/sources/${encodeURIComponent(sourceCode)}/stop`, undefined, token);
      await loadOverview(token);
    } catch (err) {
      setGlobalError(errText(err));
    }
  }

  const pollBackfill = useCallback(async () => {
    if (!token) return;
    try {
      const st = await apiSend<BackfillStatus>("/api/v1/admin/backfill-variants/status", { token });
      setBackfill(st);
      if (st.status === "running") {
        backfillPollRef.current = window.setTimeout(() => void pollBackfill(), 700);
      } else if (st.status === "done") {
        void loadOverview(token);
        backfillPollRef.current = window.setTimeout(() => setBackfill(null), 4000);
      }
    } catch (err) {
      setGlobalError(errText(err));
      setBackfill(null);
    }
  }, [token, loadOverview]);

  async function optimizeMedia() {
    if (!token) return;
    setGlobalError(null);
    try {
      const st = await apiPost<BackfillStatus>("/api/v1/admin/backfill-variants", undefined, token);
      setBackfill(st);
      if (st.status === "running") {
        backfillPollRef.current = window.setTimeout(() => void pollBackfill(), 700);
      }
    } catch (err) {
      setGlobalError(errText(err));
    }
  }

  /** Состояние дискового кэша медиа (файлы, объём, попадания, прогрев). */
  const loadCache = useCallback(async (t: string) => {
    try {
      setCacheStats(await apiSend<MediaCacheStats>("/api/v1/admin/media-cache", { token: t }));
    } catch {
      /* статистика кэша не критична для работы панели */
    }
  }, []);

  async function cacheAction(path: string) {
    if (!token) return;
    setCacheBusy(true);
    setGlobalError(null);
    try {
      await apiPost(path, undefined, token);
      await loadCache(token);
    } catch (err) {
      setGlobalError(errText(err));
    } finally {
      setCacheBusy(false);
    }
  }

  async function cleanupStorage() {
    if (!token) return;
    setGlobalError(null);
    try {
      const r = await apiPost<{ total: number; orphans: number; deleted: number }>(
        "/api/v1/admin/cleanup-storage",
        undefined,
        token,
      );
      setGlobalError(
        r.deleted > 0
          ? `Мусор в S3 удалён: ${r.deleted} объектов (проверено ${r.total})`
          : "Мусора в S3 нет (все объекты соответствуют записям).",
      );
    } catch (err) {
      setGlobalError(errText(err));
    }
  }

  async function addBoard(slug: string, name?: string | null, force = false) {
    if (!token || creating || !activeSource) return;
    setCreating(true);
    setGlobalError(null);
    setAddError(null);
    setCatalogError((prev) => {
      const next = { ...prev };
      delete next[slug];
      return next;
    });
    try {
      await apiPost<AdminBoard>(
        "/api/v1/admin/boards",
        // Источник обязателен: раздел попадает в его вкладку и обслуживается его адаптером
        { slug, name: name ?? undefined, force, source: activeSource.code },
        token,
      );
      await loadOverview(token);
      await loadCatalog(activeSource.code);
      setNewSlug("");
    } catch (err) {
      // Ошибку показываем там, где нажали: у карточки раздела в списке источника
      // и рядом с формой «Добавить раздел».
      const canForce = err instanceof ApiError && err.canForce;
      const message = errText(err);
      setCatalogError((prev) => ({ ...prev, [slug]: { message, canForce } }));
      if (!name) setAddError({ message, canForce, slug });
    } finally {
      setCreating(false);
    }
  }

  // Статистика кэша: загружаем сразу и опрашиваем, пока идёт прогрев
  useEffect(() => {
    if (!token) return;
    void loadCache(token);
    const id = window.setInterval(() => void loadCache(token), CACHE_POLL_MS);
    return () => window.clearInterval(id);
  }, [token, loadCache]);

  const totals: SystemTotals | null = overview?.totals ?? null;

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">Центр управления контентом</h2>
          <p className="mt-0.5 text-xs text-text-secondary">
            Статистика обновляется автоматически ({POLL_MS / 1000} с), без перезагрузки.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Вкладки по источникам: список приходит из реестра, поэтому новый
              источник появляется в интерфейсе без правок фронтенда */}
          <div className="flex flex-wrap items-center gap-0.5 rounded border border-line p-0.5">
            {(sources ?? []).map((s) => {
              const active = s.code === sourceCode;
              const dot = !s.is_enabled
                ? "bg-text-muted"
                : s.status.alive
                  ? "bg-accent-secondary"
                  : s.status.enabled
                    ? "bg-accent-warning"
                    : "bg-line-hover";
              return (
                <button
                  key={s.code}
                  type="button"
                  onClick={() => setSourceCode(s.code)}
                  title={`${s.title || s.code} — источник ${s.code}${s.is_enabled ? "" : " (выключен в реестре)"}`}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 text-sm transition-colors ${
                    active
                      ? "bg-ink-tertiary text-accent-primary"
                      : "text-text-secondary hover:text-white"
                  }`}
                >
                  <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
                  {s.title || s.code}
                  <span className="font-mono text-[10px] text-text-muted">
                    {formatNumber(s.boards_total)}
                  </span>
                </button>
              );
            })}
            {sources === null ? (
              <span className="px-2 py-1.5 text-xs text-text-muted">источники…</span>
            ) : null}
          </div>
          {/* Два режима работы: свои разделы и список того, что предлагает источник.
              Список читает адаптер источника (у 2ch — index.json, у сайтов —
              категории), поэтому переключатель есть у любого источника */}
          <div className="flex overflow-hidden rounded border border-line">
            <button
              type="button"
              onClick={() => setTab("boards")}
              className={`px-3 py-1.5 text-sm transition-colors ${
                tab === "boards" ? "bg-ink-tertiary text-accent-primary" : "text-text-secondary hover:text-white"
              }`}
            >
              Мои разделы
            </button>
            <button
              type="button"
              onClick={() => setTab("catalog")}
              className={`px-3 py-1.5 text-sm transition-colors ${
                tab === "catalog" ? "bg-ink-tertiary text-accent-primary" : "text-text-secondary hover:text-white"
              }`}
              title="Список разделов, которые предлагает источник: оттуда их добавляют в систему"
            >
              {activeSource?.kind === "html" ? "Разделы сайта" : "Доски форума"}
            </button>
          </div>
          <Link href="/admin/sources" className="btn-ghost px-3 py-1.5 text-xs" title="Реестр источников: расписание, лимиты, журнал прогонов">
            Источники →
          </Link>
          {tab === "boards" ? (
            <>
              <button
                type="button"
                onClick={() => void optimizeMedia()}
                disabled={backfill?.status === "running"}
                className="btn-ghost px-3 py-1.5 text-xs"
                title="Сгенерировать превью и оптимизированные версии (720p) для уже скачанных файлов"
              >
                {backfill?.status === "running" ? "Оптимизируем…" : "Оптимизировать медиа"}
              </button>
              <button
                type="button"
                onClick={() => void cleanupStorage()}
                className="btn-ghost px-3 py-1.5 text-xs"
                title="Удалить из S3 объекты, которых нет в базе"
              >
                Очистить S3
              </button>
              <button
                type="button"
                onClick={() => void resetAll()}
                className="rounded border border-accent-danger/40 px-3 py-1.5 text-xs text-accent-danger transition-colors hover:bg-accent-danger/10"
                title="Удалить все разделы и файлы"
              >
                Сбросить всё
              </button>
            </>
          ) : null}
        </div>
      </div>

      {tab === "boards" && cacheStats ? (
        <div className="mb-4 rounded border border-line bg-ink-secondary/40 px-3 py-2.5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold">Кэш медиа на диске</h3>
              <p className="mt-0.5 text-xs text-text-secondary">
                {formatBytes(cacheStats.bytes)} из {formatBytes(cacheStats.max_bytes)} (
                {cacheStats.used_percent}%) · файлов {formatNumber(cacheStats.files)} · попаданий{" "}
                {formatNumber(cacheStats.hits)} / промахов {formatNumber(cacheStats.misses)} ·
                свободно на диске {formatBytes(cacheStats.disk_free)}
              </p>
              {cacheStats.warm.status === "running" ? (
                <p className="mt-0.5 text-xs text-accent-secondary">
                  Прогрев: {formatNumber(cacheStats.warm.done)} из{" "}
                  {formatNumber(cacheStats.warm.total)}
                  {cacheStats.warm.failed
                    ? `, ошибок ${formatNumber(cacheStats.warm.failed)}`
                    : ""}
                </p>
              ) : null}
              {cacheStats.evicted_files ? (
                <p className="mt-0.5 text-xs text-text-muted">
                  Вытеснено по LRU: {formatNumber(cacheStats.evicted_files)} файлов (
                  {formatBytes(cacheStats.evicted_bytes)})
                </p>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void cacheAction("/api/v1/admin/media-cache/warm")}
                disabled={cacheBusy || cacheStats.warm.status === "running"}
                className="btn-ghost px-3 py-1.5 text-xs"
                title="Скачать в кэш всё, что есть в S3 (~16 минут на текущую библиотеку) — дальше сайт отдаёт файлы с диска"
              >
                {cacheStats.warm.status === "running" ? "Прогреваем…" : "Прогреть кэш"}
              </button>
              <button
                type="button"
                onClick={() => void cacheAction("/api/v1/admin/media-cache/sweep")}
                disabled={cacheBusy}
                className="btn-ghost px-3 py-1.5 text-xs"
                title="Удалить самые старые файлы кэша, если превышен лимит"
              >
                LRU-чистка
              </button>
              <button
                type="button"
                onClick={() => void cacheAction("/api/v1/admin/media-cache/clear")}
                disabled={cacheBusy}
                className="btn-ghost px-3 py-1.5 text-xs"
                title="Очистить кэш целиком (файлы останутся в S3 и скачаются заново)"
              >
                Очистить
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {globalError ? (
        <p className="mb-4 rounded border border-accent-danger/30 bg-red-500/10 px-3 py-2 text-sm text-accent-danger">
          {globalError}
        </p>
      ) : null}

      {backfill && backfill.status !== "idle" ? (
        <div className="mb-4 rounded border border-line bg-ink-secondary px-3 py-2">
          <div className="flex items-center justify-between gap-3 text-xs text-text-secondary">
            <span>
              {backfill.status === "running"
                ? `Оптимизируем медиа (превью, размытые превью, 720p)… пачка ${formatNumber(
                    backfill.batch_size ?? 0,
                  )}`
                : backfill.status === "done"
                  ? `Готово: обработано ${formatNumber(backfill.processed ?? 0)} из ${formatNumber(
                      backfill.total,
                    )}${
                      backfill.remaining
                        ? ` · осталось ${formatNumber(backfill.remaining)} (не удалось обработать)`
                        : ""
                    }`
                  : `Ошибка: ${backfill.error ?? "не удалось"}`}
            </span>
            <span className="shrink-0 tabular-nums">
              {backfill.status === "running"
                ? `осталось ${formatNumber(backfill.remaining ?? 0)} из ${formatNumber(backfill.total)}`
                : `${formatNumber(backfill.done)}/${formatNumber(backfill.total || 0)}`}
            </span>
          </div>
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded bg-ink-tertiary">
            <div
              className={`h-full transition-all ${
                backfill.status === "error" ? "bg-accent-danger" : "bg-accent-primary"
              }`}
              style={{
                width: `${
                  backfill.total > 0
                    ? Math.min(100, Math.round((backfill.done / backfill.total) * 100))
                    : backfill.status === "running"
                      ? 10
                      : 0
                }%`,
              }}
            />
          </div>
        </div>
      ) : null}

      {tab === "boards" ? (
        <>
          {totals ? <TotalsBar totals={totals} /> : null}
          {activeSource ? (
            <QueueStatus
              source={activeSource}
              status={parserStatus}
              boards={(overview?.boards ?? []).filter((b) => b.source_id === activeSource.id)}
              onStart={() => void startParser()}
              onStop={() => void stopParser()}
            />
          ) : null}

          <>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                // Принимаем и «hc», и «/hc», и ссылку — лишние слеши убираем сразу
                const slug = newSlug.trim().toLowerCase().replace(/^\/+|\/+$/g, "");
                if (slug) void addBoard(slug);
              }}
              className="my-5 flex flex-wrap items-center gap-2"
            >
              <input
                value={newSlug}
                onChange={(e) => setNewSlug(e.target.value)}
                placeholder={
                  activeSource?.kind === "html"
                    ? "slug раздела источника, например modeli"
                    : "slug новой доски, например abc или /abc"
                }
                className="w-56 rounded border border-line bg-ink-secondary px-3 py-2 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-accent-primary"
              />
              <button type="submit" disabled={creating || !newSlug.trim()} className="btn-ghost">
                {creating ? <SpinnerIcon className="h-4 w-4" /> : <PlusIcon className="h-4 w-4" />}
                Добавить раздел
              </button>
            </form>

            {addError ? (
              <div className="mb-5 rounded border border-accent-danger/30 bg-red-500/5 px-3 py-2 text-sm text-accent-danger">
                <div>{addError.message}</div>
                {addError.canForce ? (
                  <button
                    type="button"
                    disabled={creating}
                    onClick={() => void addBoard(addError.slug, undefined, true)}
                    className="mt-2 rounded border border-line px-2.5 py-1.5 text-xs text-text-secondary transition-colors hover:text-text-primary"
                    title="Раздел появится в списке, но качаться не будет, пока источник не отдаст его каталог"
                  >
                    Добавить всё равно
                  </button>
                ) : null}
              </div>
            ) : null}

            {activeSource && activeSource.boards_total === 0 ? (
              <p className="my-5 rounded border border-dashed border-line px-3 py-6 text-center text-sm text-text-secondary">
                Разделов пока нет. Откройте вкладку{" "}
                <button type="button" onClick={() => setTab("catalog")} className="text-accent-primary">
                  «{activeSource.kind === "html" ? "Разделы сайта" : "Доски форума"}»
                </button>{" "}
                и добавьте нужные: внутри раздела появится список «тредов» (у сайтов —
                записей), и их тоже можно включать поштучно.
              </p>
            ) : null}
          </>

          <BoardsTable
            boards={visibleBoards}
            loading={loading}
            parserStatus={parserStatus}
            busyKey={busyKey}
            rowError={rowError}
            onPatch={patch}
            onMove={moveBoard}
            onRename={async (slug, title) => {
              await patch(slug, { title });
            }}
            onDelete={async (slug) => {
              await removeBoard(slug);
            }}
          />
        </>
      ) : (
        <CatalogTab
          items={catalog}
          loading={loading}
          query={catalogQuery}
          onQuery={setCatalogQuery}
          onRefresh={() => {
            if (sourceCode) void loadCatalog(sourceCode);
          }}
          onAdd={addBoard}
          onRemove={async (slug) => {
            await removeBoard(slug);
            // Список перечитываем: у добавленного раздела появились счётчики
            if (sourceCode) void loadCatalog(sourceCode);
          }}
          addError={catalogError}
          hintLabel={activeSource?.kind === "html" ? "записей на сайте" : "на форуме"}
        />
      )}
    </div>
  );
}

/** Строка общих цифр системы. */
function TotalsBar({ totals }: { totals: SystemTotals }) {
  const items: Array<[string, string]> = [
    ["Доски", `${formatNumber(totals.boards_total)} (парсим ${formatNumber(totals.boards_parsed)})`],
    ["Треды", `${formatNumber(totals.threads_active)} (парсим ${formatNumber(totals.threads_parsing)})`],
  ["В очереди", formatNumber(totals.threads_pending ?? 0)],
  ["Мёртвых", formatNumber(totals.threads_dead ?? 0)],
    ["Файлов в БД", formatNumber(totals.media_total)],
    ["В S3", formatNumber(totals.media_in_s3)],
    ["Скачано", formatNumber(totals.media_downloaded)],
    ["Пропущено", formatNumber(totals.media_missing)],
    ["В каталоге", formatNumber(totals.files_in_catalog)],
    ["Просмотры", formatNumber(totals.views_total)],
    ["Скачивания", formatNumber(totals.downloads_total)],
  ];
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      {items.map(([label, value]) => (
        <div key={label} className="rounded border border-line bg-ink-secondary px-3 py-2">
          <div className="text-[11px] uppercase tracking-wider text-text-secondary">{label}</div>
          <div className="mt-0.5 text-base font-semibold tabular-nums text-text-primary">{value}</div>
        </div>
      ))}
    </div>
  );
}

/** Статус прогона источника: контейнер, включение, текущая доска и очередь. */
function QueueStatus({
  source,
  status,
  boards,
  onStart,
  onStop,
}: {
  source: SourceInfo;
  status: ParserStatus | null;
  boards: AdminBoard[];
  onStart: () => void;
  onStop: () => void;
}) {
  const parsed = boards.filter((b) => b.parse_enabled);
  const current = status?.current_board ?? null;
  const up = Boolean(status?.up);
  const alive = Boolean(status?.alive);
  const enabled = Boolean(status?.enabled);

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 rounded border border-line bg-ink-secondary px-3 py-2 text-sm">
      <span className="flex items-center gap-2">
        <span
          className={`h-2 w-2 rounded-full ${
            !source.is_enabled ? "bg-neutral-600" : up ? (alive ? "bg-accent-secondary" : "bg-amber-400") : "bg-neutral-600"
          }`}
        />
        <span
          className={
            !source.is_enabled
              ? "text-text-secondary"
              : up
                ? alive
                  ? "text-text-primary"
                  : "text-accent-primary"
                : "text-text-secondary"
          }
        >
          {!source.is_enabled
            ? `Источник ${source.code} выключен в реестре`
            : !up
              ? `Контейнер ${source.code} не отвечает`
              : alive
                ? `Прогон «${source.title || source.code}» работает`
                : `Прогон «${source.title || source.code}» на паузе`}
        </span>
      </span>

      {!source.is_enabled ? (
        <Link href="/admin/sources" className="text-xs text-accent-primary">
          открыть реестр источников →
        </Link>
      ) : !up ? (
        <span className="text-xs text-text-muted">
          контейнер не отвечает — проверьте: docker compose ... logs parser-{source.code}
        </span>
      ) : enabled ? (
        <button type="button" onClick={onStop} className="btn-ghost px-3 py-1 text-xs">
          Остановить
        </button>
      ) : (
        <button type="button" onClick={onStart} className="btn-primary px-3 py-1 text-xs">
          Запустить прогон
        </button>
      )}

      {alive && current ? (
        <span className="text-text-primary">
          сейчас парсит: <b className="text-accent-primary">/{current}</b>
        </span>
      ) : null}

      <span className="text-text-secondary">
        очередь ({formatNumber(parsed.length)}):{" "}
        {parsed.length === 0 ? (
          <span className="text-text-muted">нет досок с включённым парсингом</span>
        ) : (
          parsed.map((b, i) => (
            <span key={b.slug}>
              {i > 0 ? " → " : ""}
              <span className={b.slug === current ? "font-semibold text-accent-primary" : "text-text-secondary"}>
                /{b.slug}
              </span>
            </span>
          ))
        )}
      </span>
    </div>
  );
}
