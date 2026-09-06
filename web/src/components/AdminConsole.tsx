"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { PlusIcon, SpinnerIcon } from "@/components/icons";
import { BoardsTable, ForumTab } from "@/components/AdminViews";
import { ApiError, apiDelete, apiPatch, apiPost, apiSend } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import type { AdminBoard, AdminOverview, ForumBoard, SystemTotals } from "@/lib/types";

const TOKEN_KEY = "admin_token";
const POLL_MS = 7000;

type Tab = "boards" | "forum";

function readToken(): string {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(TOKEN_KEY) ?? "";
}

function errText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return err.detail;
  return err instanceof Error ? err.message : "Ошибка";
}

export default function AdminConsole() {
  const [token, setToken] = useState<string>(readToken);
  const [loginInput, setLoginInput] = useState("");
  const [tab, setTab] = useState<Tab>("boards");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [forum, setForum] = useState<ForumBoard[] | null>(null);
  const [forumQuery, setForumQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const [codes, setCodes] = useState<Record<string, string>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [newSlug, setNewSlug] = useState("");
  const [creating, setCreating] = useState(false);

  const loadOverview = useCallback(
    async (t: string) => {
      try {
        const data = await apiSend<AdminOverview>("/api/v1/admin/overview", { token: t });
        setOverview(data);
        setGlobalError(null);
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          window.sessionStorage.removeItem(TOKEN_KEY);
          setToken("");
          setGlobalError("Неверный admin-токен. Войдите заново.");
        } else {
          setGlobalError(errText(err));
        }
      }
    },
    [],
  );

  const logout = useCallback(() => {
    window.sessionStorage.removeItem(TOKEN_KEY);
    setToken("");
    setOverview(null);
    setForum(null);
  }, []);

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

  function login(e: React.FormEvent) {
    e.preventDefault();
    const t = loginInput.trim();
    if (!t) return;
    window.sessionStorage.setItem(TOKEN_KEY, t);
    setToken(t);
  }

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

  async function setCode(slug: string) {
    const code = (codes[slug] ?? "").trim();
    if (!code) return;
    await patch(slug, { access_code: code });
    setCodes((prev) => ({ ...prev, [slug]: "" }));
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
    if (!window.confirm("Полный сброс: удалить ВСЕ разделы и ВСЕ файлы из хранилища (B2)?")) return;
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

  async function cleanupB2() {
    if (!token) return;
    setGlobalError(null);
    try {
      const r = await apiPost<{ total: number; orphans: number; deleted: number }>(
        "/api/v1/admin/cleanup-b2",
        undefined,
        token,
      );
      setGlobalError(
        r.deleted > 0
          ? `Мусор в B2 удалён: ${r.deleted} объектов (проверено ${r.total})`
          : "Мусора в B2 нет (все объекты соответствуют записям).",
      );
    } catch (err) {
      setGlobalError(errText(err));
    }
  }

  async function addBoard(slug: string, name?: string | null) {
    if (!token || creating) return;
    setCreating(true);
    setGlobalError(null);
    try {
      await apiPost<AdminBoard>("/api/v1/admin/boards", { slug, name: name ?? undefined }, token);
      await loadOverview(token);
      setForum((prev) =>
        prev
          ? prev.map((f) => (f.slug === slug ? { ...f, in_db: true, parse_enabled: false } : f))
          : prev,
      );
    } catch (err) {
      setGlobalError(errText(err));
    } finally {
      setCreating(false);
    }
  }

  const ready = useMemo(() => Boolean(token), [token]);
  const totals: SystemTotals | null = overview?.totals ?? null;

  if (!ready) {
    return (
      <div className="mx-auto max-w-md py-10">
        <h2 className="text-xl font-bold">Вход в админ-панель</h2>
        <p className="mt-1 text-sm text-neutral-500">Введите admin-токен (ADMIN_TOKEN из .env).</p>
        <form onSubmit={login} className="mt-5 flex flex-col gap-3">
          <input
            type="password"
            value={loginInput}
            onChange={(e) => setLoginInput(e.target.value)}
            placeholder="Admin-токен"
            autoFocus
            className="rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 outline-none transition-colors placeholder:text-neutral-600 focus:border-amber-500"
          />
          <button type="submit" disabled={!loginInput.trim()} className="btn-primary">
            Войти
          </button>
          {globalError ? <p className="text-sm text-red-400">{globalError}</p> : null}
        </form>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">Центр управления контентом</h2>
          <p className="mt-0.5 text-xs text-neutral-500">
            Статистика обновляется автоматически ({POLL_MS / 1000} с), без перезагрузки.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex overflow-hidden rounded-lg border border-neutral-800">
            <button
              type="button"
              onClick={() => setTab("boards")}
              className={`px-3 py-1.5 text-sm transition-colors ${
                tab === "boards" ? "bg-neutral-800 text-amber-300" : "text-neutral-400 hover:text-white"
              }`}
            >
              Мои разделы
            </button>
            <button
              type="button"
              onClick={() => setTab("forum")}
              className={`px-3 py-1.5 text-sm transition-colors ${
                tab === "forum" ? "bg-neutral-800 text-amber-300" : "text-neutral-400 hover:text-white"
              }`}
            >
              Доски форума
            </button>
          </div>
          <button type="button" onClick={logout} className="btn-ghost px-3 py-1.5 text-xs">
            Выйти
          </button>
          {tab === "boards" ? (
            <>
              <button
                type="button"
                onClick={() => void cleanupB2()}
                className="btn-ghost px-3 py-1.5 text-xs"
                title="Удалить из B2 объекты, которых нет в базе"
              >
                Очистить B2
              </button>
              <button
                type="button"
                onClick={() => void resetAll()}
                className="rounded-lg border border-red-500/40 px-3 py-1.5 text-xs text-red-400 transition-colors hover:bg-red-500/10"
                title="Удалить все разделы и файлы"
              >
                Сбросить всё
              </button>
            </>
          ) : null}
        </div>
      </div>

      {globalError ? (
        <p className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {globalError}
        </p>
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
              if (newSlug.trim()) void addBoard(newSlug.trim().toLowerCase());
            }}
            className="my-5 flex flex-wrap items-center gap-2"
          >
            <input
              value={newSlug}
              onChange={(e) => setNewSlug(e.target.value)}
              placeholder="slug новой доски, например abc"
              className="w-56 rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 outline-none transition-colors placeholder:text-neutral-600 focus:border-amber-500"
            />
            <button type="submit" disabled={creating || !newSlug.trim()} className="btn-ghost">
              {creating ? <SpinnerIcon className="h-4 w-4" /> : <PlusIcon className="h-4 w-4" />}
              Добавить раздел
            </button>
          </form>

          <BoardsTable
            boards={overview?.boards ?? null}
            loading={loading}
            busyKey={busyKey}
            codes={codes}
            rowError={rowError}
            onSetCodes={setCodes}
            onPatch={patch}
            onSetCode={setCode}
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
        />
      )}
    </div>
  );
}

/** Строка общих цифр системы. */
function TotalsBar({ totals }: { totals: SystemTotals }) {
  const items: Array<[string, string]> = [
    ["Доски", `${formatNumber(totals.boards_total)} (парсим ${formatNumber(totals.boards_parsed)})`],
    ["Треды", formatNumber(totals.threads_active)],
    ["Файлов в БД", formatNumber(totals.media_total)],
    ["В B2", formatNumber(totals.media_in_b2)],
    ["Скачано", formatNumber(totals.media_downloaded)],
    ["Пропущено", formatNumber(totals.media_missing)],
    ["В каталоге", formatNumber(totals.files_in_catalog)],
    ["Просмотры", formatNumber(totals.views_total)],
    ["Скачивания", formatNumber(totals.downloads_total)],
  ];
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      {items.map(([label, value]) => (
        <div key={label} className="rounded-xl border border-neutral-800 bg-neutral-900/40 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wider text-neutral-500">{label}</div>
          <div className="mt-0.5 text-base font-semibold tabular-nums text-neutral-100">{value}</div>
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
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-neutral-800 bg-neutral-900/40 px-3 py-2 text-sm">
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
                ? "text-neutral-200"
                : "text-amber-300"
              : "text-neutral-500"
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
        <span className="text-xs text-neutral-600">
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
        <span className="text-neutral-300">
          сейчас парсит: <b className="text-amber-300">/{current}</b>
        </span>
      ) : null}

      <span className="text-neutral-500">
        очередь ({formatNumber(parsed.length)}):{" "}
        {parsed.length === 0 ? (
          <span className="text-neutral-600">нет досок с включённым парсингом</span>
        ) : (
          parsed.map((b, i) => (
            <span key={b.slug}>
              {i > 0 ? " → " : ""}
              <span className={b.slug === current ? "font-semibold text-amber-300" : "text-neutral-400"}>
                /{b.slug}
              </span>
            </span>
          ))
        )}
      </span>
    </div>
  );
}
