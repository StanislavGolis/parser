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
  // Инструкция раскрывается по кнопке, а редкие операции (кэш, оптимизация,
  // чистка, сброс) живут в отдельном свёрнутом блоке внизу: повседневные шаги
  // не должны тонуть в обслуживании.
  const [showHelp, setShowHelp] = useState(false);
  const [showMaintenance, setShowMaintenance] = useState(false);

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

  async function patch(slug: string, body: Record<string, unknown>): Promise<boolean> {
    if (!token) return false;
    setBusyKey(slug);
    setRowError((prev) => ({ ...prev, [slug]: "" }));
    try {
      const updated = await apiPatch<AdminBoard>(
        `/api/v1/admin/boards/${encodeURIComponent(slug)}`,
        body,
        token,
      );
      replaceBoard(updated);
      return true;
    } catch (err) {
      setRowError((prev) => ({ ...prev, [slug]: errText(err) }));
      return false;
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
      {/* Шапка: сразу видно, что это за экран и в каком порядке действовать */}
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">Центр управления контентом</h2>
          <p className="mt-0.5 text-xs text-text-secondary">
            Порядок работы: <b className="text-text-secondary">источник → раздел → треды</b>. Цифры
            обновляются каждые {POLL_MS / 1000} с, без перезагрузки.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowHelp((v) => !v)}
          className="btn-ghost px-3 py-1.5 text-xs"
          title="Короткая инструкция: как добавить раздел и включить загрузку файлов"
        >
          {showHelp ? "Скрыть инструкцию" : "Как это работает"}
        </button>
      </div>

      {showHelp ? <ConsoleHelp kind={activeSource?.kind ?? null} /> : null}

      {/* Шаги 1–2: что забираем (источник) и откуда берём список разделов */}
      <div className="grid gap-3 lg:grid-cols-2">
        <StepCard
          step={1}
          title="Источник"
          hint="Чей контент забираем. Точка слева — состояние его прогона (серый — выключен)."
        >
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
          <Link
            href="/admin/content?tab=sources"
            className="mt-2 inline-block text-xs text-accent-primary"
            title="Реестр источников: расписание, лимиты, журнал прогонов"
          >
            реестр источников →
          </Link>
        </StepCard>

        <StepCard
          step={2}
          title="Раздел"
          hint="«Мои разделы» — то, что уже в системе и качается; в списке источника — то, что можно добавить."
        >
          <div className="flex overflow-hidden rounded border border-line">
            <button
              type="button"
              onClick={() => setTab("boards")}
              title="Разделы, подключённые к системе: ими управляют парсинг, видимость и премиум"
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
              title="Список разделов, которые предлагает источник: отсюда их добавляют в систему"
            >
              {activeSource?.kind === "html" ? "Разделы сайта" : "Доски форума"}
            </button>
          </div>
          <p className="mt-2 text-xs text-text-muted">
        Добавили раздел — он попадёт в «Мои разделы», внутри включите «Парсить» и нажмите
        «Сканировать треды».
      </p>
        </StepCard>
      </div>

      <p className="mt-2 text-xs text-text-muted">
        <b className="text-text-secondary">Шаг 3.</b> Ниже — разделы и их треды: внутри раздела
        нажмите «Сканировать треды» (подтянет список), у нужных тредов включите «Парсить» —
        файлы скачает прогон источника.
      </p>

      {/* Состояние дискового кэша переехало в блок «Обслуживание» внизу страницы:
          это редкая операция, ей не место среди повседневных шагов. */}

      {globalError ? (
        <p className="mb-4 rounded border border-accent-danger/30 bg-red-500/10 px-3 py-2 text-sm text-accent-danger">
          {globalError}
        </p>
      ) : null}

      {/* Прогресс оптимизации медиа тоже переехал в блок «Обслуживание» */}

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

      {/* Шаг 3 — треды: редкие операции вынесены вниз, чтобы не мешать работе */}
      {tab === "boards" ? (
        <ConsoleMaintenance
          open={showMaintenance}
          onToggle={() => setShowMaintenance((v) => !v)}
          cache={cacheStats}
          cacheBusy={cacheBusy}
          backfill={backfill}
          onCacheAction={(path) => void cacheAction(path)}
          onOptimize={() => void optimizeMedia()}
          onCleanup={() => void cleanupStorage()}
          onReset={() => void resetAll()}
        />
      ) : null}
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
        <Link href="/admin/content?tab=sources" className="text-xs text-accent-primary">
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

/** Шаг интерфейса: номер, заголовок, подсказка и содержимое. */
function StepCard({
  step,
  title,
  hint,
  children,
}: {
  step: number;
  title: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded border border-line bg-ink-secondary/40 p-3">
      <div className="flex items-center gap-2">
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-ink-tertiary font-mono text-[11px] text-accent-primary">
          {step}
        </span>
        <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
      </div>
      <p className="mt-1 text-xs text-text-muted">{hint}</p>
      <div className="mt-2">{children}</div>
    </section>
  );
}

/** Краткая инструкция: порядок действий, открывается кнопкой «Как это работает». */
function ConsoleHelp({ kind }: { kind: string | null }) {
  const units = kind === "html" ? "записи" : "треды";
  return (
    <ol className="mb-4 space-y-1.5 rounded border border-line bg-ink-secondary/30 px-4 py-3 text-xs text-text-secondary">
      <li>
        <b className="text-text-primary">1. Источник.</b> Чей контент забираем. Источники
        независимы: у каждого свой прогон, расписание и лимиты (реестр — ссылка слева).
      </li>
      <li>
        <b className="text-text-primary">2. Раздел.</b> «Разделы сайта» / «Доски форума» —
        список того, что предлагает источник; «Добавить» переносит раздел в «Мои разделы».
        Свой слаг можно ввести в поле вручную.
      </li>
      <li>
        <b className="text-text-primary">3. {units}.</b> Внутри раздела нажмите «Сканировать
        треды» — появится список {units} источника. У нужных включите «Парсить» (и
        «Показать», если раздел скрыт): они встают в очередь, файлы качает прогон источника.
      </li>
      <li>
        <b className="text-text-primary">4. Что дальше.</b> Текущий раздел и очередь видны в
        строке прогона, «Остановить» ставит его на паузу. Редкие операции (кэш, оптимизация
        превью, чистка S3) — в блоке «Обслуживание» в самом низу.
      </li>
    </ol>
  );
}

/** Редкие операции: кэш, оптимизация превью, чистка S3 и сброс. Свёрнут по умолчанию. */
function ConsoleMaintenance({
  open,
  onToggle,
  cache,
  cacheBusy,
  backfill,
  onCacheAction,
  onOptimize,
  onCleanup,
  onReset,
}: {
  open: boolean;
  onToggle: () => void;
  cache: MediaCacheStats | null;
  cacheBusy: boolean;
  backfill: BackfillStatus | null;
  onCacheAction: (path: string) => void;
  onOptimize: () => void;
  onCleanup: () => void;
  onReset: () => void;
}) {
  return (
    <section className="mt-8 rounded border border-line bg-ink-secondary/20 px-3 py-2.5">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start justify-between gap-3 text-left"
        title="Оптимизация превью, дисковый кэш, чистка хранилища и полный сброс. Нужны редко — открывайте осознанно."
      >
        <span>
          <span className="text-sm font-semibold text-text-primary">Обслуживание</span>
          <span className="mt-0.5 block text-xs text-text-muted">
            Оптимизация превью, дисковый кэш, чистка S3, полный сброс. Для повседневной работы
            не нужно.
          </span>
        </span>
        <span className="shrink-0 font-mono text-[11px] text-text-muted">
          {open ? "скрыть" : "показать"}
        </span>
      </button>

      {open ? (
        <div className="mt-3 space-y-3 border-t border-line pt-3">
          {backfill && backfill.status !== "idle" ? (
            <div className="rounded border border-line bg-ink-secondary px-3 py-2">
              <div className="flex items-center justify-between gap-3 text-xs text-text-secondary">
                <span>
                  {backfill.status === "running"
                    ? `Оптимизируем медиа (превью, размытые превью, 720p)… пачка ${formatNumber(
                        backfill.batch_size ?? 0,
                      )}`
                    : backfill.status === "done"
                      ? `Готово: обработано ${formatNumber(backfill.processed ?? 0)} из ${formatNumber(
                          backfill.total,
                        )}`
                      : `Ошибка: ${backfill.error ?? "не удалось"}`}
                </span>
                <span className="shrink-0 tabular-nums">
                  {formatNumber(backfill.done)}/{formatNumber(backfill.total || 0)}
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
          {cache ? (
            <div className="rounded border border-line bg-ink-secondary px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-text-secondary">
                  <b className="text-text-primary">Кэш медиа на диске:</b>{" "}
                  {formatBytes(cache.bytes)} из {formatBytes(cache.max_bytes)} (
                  {cache.used_percent}%) · файлов {formatNumber(cache.files)} · попаданий{" "}
                  {formatNumber(cache.hits)} / промахов {formatNumber(cache.misses)} · свободно{" "}
                  {formatBytes(cache.disk_free)}
                  {cache.warm.status === "running"
                    ? ` · прогрев: ${formatNumber(cache.warm.done)} из ${formatNumber(cache.warm.total)}`
                    : ""}
                </p>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => onCacheAction("/api/v1/admin/media-cache/warm")}
                    disabled={cacheBusy || cache.warm.status === "running"}
                    className="btn-ghost px-3 py-1.5 text-xs"
                    title="Скачать в кэш всё, что есть в S3 — дальше сайт отдаёт файлы с диска, а не из S3"
                  >
                    {cache.warm.status === "running" ? "Прогреваем…" : "Прогреть кэш"}
                  </button>
                  <button
                    type="button"
                    onClick={() => onCacheAction("/api/v1/admin/media-cache/sweep")}
                    disabled={cacheBusy}
                    className="btn-ghost px-3 py-1.5 text-xs"
                    title="Удалить самые старые файлы кэша, если превышен лимит"
                  >
                    LRU-чистка
                  </button>
                  <button
                    type="button"
                    onClick={() => onCacheAction("/api/v1/admin/media-cache/clear")}
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
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onOptimize}
              disabled={backfill?.status === "running"}
              className="btn-ghost px-3 py-1.5 text-xs"
              title="Сгенерировать превью и оптимизированные версии (720p) для уже скачанных файлов"
            >
              {backfill?.status === "running" ? "Оптимизируем…" : "Оптимизировать медиа"}
            </button>
            <button
              type="button"
              onClick={onCleanup}
              className="btn-ghost px-3 py-1.5 text-xs"
              title="Удалить из S3 объекты, которых нет в базе (безопасно: сверяется с записями)"
            >
              Очистить S3
            </button>
            <button
              type="button"
              onClick={onReset}
              className="rounded border border-accent-danger/40 px-3 py-1.5 text-xs text-accent-danger transition-colors hover:bg-accent-danger/10"
              title="Удалить ВСЕ разделы и файлы: и из базы, и из хранилища. Действие необратимо"
            >
              Сбросить всё
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

