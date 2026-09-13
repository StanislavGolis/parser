"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { PlusIcon, SpinnerIcon } from "@/components/icons";
import { BoardsTable, ForumTab } from "@/components/AdminViews";
import { ApiError, apiDelete, apiPatch, apiPost, apiSend } from "@/lib/api";
import { useAdminToken } from "@/lib/adminAuth";
import { formatBytes, formatNumber } from "@/lib/format";
import type {
  AdminBoard,
  AdminOverview,
  BackfillStatus,
  ForumBoard,
  MediaCacheStats,
  ParserStatus,
  SystemTotals,
} from "@/lib/types";

const POLL_MS = 2000; // сводка (агрегаты по доскам) — раз в 2 c
const PARSER_POLL_MS = 1000; // статус парсера (лёгкий запрос) — раз в 1 c
const CACHE_POLL_MS = 10000; // состояние кэша медиа (обход каталога) — раз в 10 c

type Tab = "boards" | "forum";

function errText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return err.detail;
  return err instanceof Error ? err.message : "Ошибка";
}

export default function AdminConsole() {
  const { token, logout } = useAdminToken();
  const [tab, setTab] = useState<Tab>("boards");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [forum, setForum] = useState<ForumBoard[] | null>(null);
  const [forumQuery, setForumQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [newSlug, setNewSlug] = useState("");
  const [creating, setCreating] = useState(false);
  const [addError, setAddError] = useState<{ message: string; canForce: boolean; slug: string } | null>(
    null,
  );
  const [forumError, setForumError] = useState<Record<string, { message: string; canForce: boolean }>>(
    {},
  );
  const [backfill, setBackfill] = useState<BackfillStatus | null>(null);
  const backfillPollRef = useRef<number | null>(null);
  const [parserStatus, setParserStatus] = useState<ParserStatus | null>(null);
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

  const loadParserStatus = useCallback(async (t: string) => {
    try {
      setParserStatus(await apiSend<ParserStatus>("/api/v1/admin/parser/status", { token: t }));
    } catch {
      /* тихо игнорируем — следующий тик повторит */
    }
  }, []);

  // Лёгкий статус парсера — раз в секунду (живость + прогресс текущего треда)
  useEffect(() => {
    if (!token) return;
    void loadParserStatus(token);
    const id = window.setInterval(() => void loadParserStatus(token), PARSER_POLL_MS);
    return () => window.clearInterval(id);
  }, [token, loadParserStatus]);

  const loadForum = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setGlobalError(null);
    try {
      const data = await apiSend<ForumBoard[]>("/api/v1/admin/forum", { token });
      setForum(data);
    } catch (err) {
      setGlobalError(errText(err));
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (token && tab === "forum" && forum === null) void loadForum();
  }, [token, tab, forum, loadForum]);

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
    if (!token) return;
    try {
      await apiPost("/api/v1/admin/parser/start", undefined, token);
      setGlobalError(null);
      await loadOverview(token);
    } catch (err) {
      setGlobalError(errText(err));
    }
  }

  async function stopParser() {
    if (!token) return;
    try {
      await apiPost("/api/v1/admin/parser/stop", undefined, token);
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
    if (!token || creating) return;
    setCreating(true);
    setGlobalError(null);
    setAddError(null);
    setForumError((prev) => {
      const next = { ...prev };
      delete next[slug];
      return next;
    });
    try {
      await apiPost<AdminBoard>(
        "/api/v1/admin/boards",
        { slug, name: name ?? undefined, force },
        token,
      );
      await loadOverview(token);
      setForum((prev) =>
        prev
          ? prev.map((f) => (f.slug === slug ? { ...f, in_db: true, parse_enabled: false } : f))
          : prev,
      );
      setNewSlug("");
    } catch (err) {
      // Ошибку показываем там, где нажали: у карточки раздела на «Досках форума»
      // и рядом с формой «Добавить раздел» на «Моих разделах».
      const canForce = err instanceof ApiError && err.canForce;
      const message = errText(err);
      setForumError((prev) => ({ ...prev, [slug]: { message, canForce } }));
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
              onClick={() => setTab("forum")}
              className={`px-3 py-1.5 text-sm transition-colors ${
                tab === "forum" ? "bg-ink-tertiary text-accent-primary" : "text-text-secondary hover:text-white"
              }`}
            >
              Доски форума
            </button>
          </div>
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
          {overview ? (
            <QueueStatus
              overview={overview}
              onStart={() => void startParser()}
              onStop={() => void stopParser()}
            />
          ) : null}

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
              placeholder="slug новой доски, например abc или /abc"
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
                  title="Раздел появится в списке с бейджем «каталог недоступен»; парситься он не будет, пока 2ch не откроет доступ"
                >
                  Добавить всё равно
                </button>
              ) : null}
            </div>
          ) : null}

          <BoardsTable
            boards={overview?.boards ?? null}
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
        <ForumTab
          forum={forum}
          loading={loading}
          query={forumQuery}
          onQuery={setForumQuery}
          onRefresh={() => void loadForum()}
          onAdd={addBoard}
          onRemove={async (slug) => {
            await removeBoard(slug);
            setForum((prev) => (prev ? prev.map((f) => (f.slug === slug ? { ...f, in_db: false } : f)) : prev));
          }}
          addError={forumError}
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

/** Статус парсера: демон, включение, текущая доска и очередь парсинга. */
function QueueStatus({
  overview,
  onStart,
  onStop,
}: {
  overview: AdminOverview;
  onStart: () => void;
  onStop: () => void;
}) {
  const parsed = overview.boards.filter((b) => b.parse_enabled);
  const current = overview.parser_current_board;

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 rounded border border-line bg-ink-secondary px-3 py-2 text-sm">
      <span className="flex items-center gap-2">
        <span
          className={`h-2 w-2 rounded-full ${
            overview.parser_up
              ? overview.parser_alive
                ? "bg-emerald-400"
                : "bg-amber-400"
              : "bg-neutral-600"
          }`}
        />
        <span
          className={
            overview.parser_up
              ? overview.parser_alive
                ? "text-text-primary"
                : "text-accent-primary"
              : "text-text-secondary"
          }
        >
          {!overview.parser_up
            ? "Парсер-демон не запущен"
            : overview.parser_alive
              ? "Парсер работает"
              : "Парсер на паузе"}
        </span>
      </span>

      {!overview.parser_up ? (
        <span className="text-xs text-text-muted">
          демон не запущен — выполните: docker compose -f docker-compose.prod.yml start parser
        </span>
      ) : overview.parser_enabled ? (
        <button type="button" onClick={onStop} className="btn-ghost px-3 py-1 text-xs">
          Остановить
        </button>
      ) : (
        <button type="button" onClick={onStart} className="btn-primary px-3 py-1 text-xs">
          Запустить парсер
        </button>
      )}

      {overview.parser_alive && current ? (
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
