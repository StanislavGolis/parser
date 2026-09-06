"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { LockIcon, PlusIcon, SpinnerIcon } from "@/components/icons";
import { ApiError, apiPatch, apiPost, apiSend } from "@/lib/api";
import { formatNumber, plural } from "@/lib/format";
import type { AdminBoard } from "@/lib/types";

const TOKEN_KEY = "admin_token";

function readToken(): string {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(TOKEN_KEY) ?? "";
}

/** Переключатель-«галочка». */
function Switch({
  checked,
  onChange,
  label,
  title,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
  title?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      title={title}
      onClick={onChange}
      className={`inline-flex shrink-0 items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors ${
        checked
          ? "border-amber-500/50 bg-amber-500/15 text-amber-300"
          : "border-neutral-700 bg-neutral-800/40 text-neutral-400 hover:text-neutral-200"
      }`}
    >
      <span
        className={`h-2 w-2 rounded-full ${checked ? "bg-amber-400" : "bg-neutral-600"}`}
      />
      {label}
    </button>
  );
}

export default function AdminConsole() {
  const [token, setToken] = useState<string>(readToken);
  const [loginInput, setLoginInput] = useState("");
  const [boards, setBoards] = useState<AdminBoard[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});

  const [codes, setCodes] = useState<Record<string, string>>({}); // slug -> введённый код
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [newSlug, setNewSlug] = useState("");
  const [creating, setCreating] = useState(false);

  const logout = useCallback(() => {
    window.sessionStorage.removeItem(TOKEN_KEY);
    setToken("");
    setBoards(null);
  }, []);

  const fetchBoards = useCallback(
    async (t: string) => {
      setLoading(true);
      setGlobalError(null);
      try {
        const data = await apiSend<AdminBoard[]>("/api/v1/admin/boards", { token: t });
        setBoards(data);
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          window.sessionStorage.removeItem(TOKEN_KEY);
          setToken("");
          setGlobalError("Неверный admin-токен. Войдите заново.");
        } else {
          setGlobalError(err instanceof Error ? err.message : "Ошибка загрузки");
        }
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (token) void fetchBoards(token);
  }, [token, fetchBoards]);

  function login(e: React.FormEvent) {
    e.preventDefault();
    const t = loginInput.trim();
    if (!t) return;
    window.sessionStorage.setItem(TOKEN_KEY, t);
    setToken(t);
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
      setBoards((prev) => (prev ? prev.map((b) => (b.slug === slug ? updated : b)) : prev));
    } catch (err) {
      const msg =
        err instanceof ApiError && err.detail
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Ошибка сохранения";
      setRowError((prev) => ({ ...prev, [slug]: msg }));
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

  async function createBoard() {
    const slug = newSlug.trim().toLowerCase();
    if (!slug || creating) return;
    setCreating(true);
    setGlobalError(null);
    try {
      await apiPost<AdminBoard>("/api/v1/admin/boards", { slug }, token);
      setNewSlug("");
      if (token) await fetchBoards(token);
    } catch (err) {
      const msg =
        err instanceof ApiError && err.detail
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Ошибка создания";
      setGlobalError(msg);
    } finally {
      setCreating(false);
    }
  }

  const ready = useMemo(() => Boolean(token), [token]);

  if (!ready) {
    return (
      <div className="mx-auto max-w-md py-10">
        <h2 className="text-xl font-bold">Вход в админ-панель</h2>
        <p className="mt-1 text-sm text-neutral-500">
          Введите admin-токен (ADMIN_TOKEN из .env).
        </p>
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
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">Управление разделами</h2>
          <p className="mt-1 text-sm text-neutral-500">
            Галочки сохраняются сразу. Изменения парсинга парсер подхватит в следующем цикле.
          </p>
        </div>
        <button type="button" onClick={logout} className="btn-ghost px-3 py-1.5 text-xs">
          Выйти
        </button>
      </div>

      {globalError ? (
        <p className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {globalError}
        </p>
      ) : null}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void createBoard();
        }}
        className="mb-6 flex flex-wrap items-center gap-2"
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

      {loading && !boards ? (
        <p className="py-10 text-center text-sm text-neutral-400">Загружаем разделы…</p>
      ) : !boards || boards.length === 0 ? (
        <p className="py-10 text-center text-sm text-neutral-500">
          Разделов пока нет. Добавьте первый или запустите парсер — он создаст доски из
          BOARDS_TO_PARSE.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-separate border-spacing-0 text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-neutral-500">
                <th className="border-b border-neutral-800 px-3 py-2 font-medium">Раздел</th>
                <th className="border-b border-neutral-800 px-3 py-2 font-medium">Парсить</th>
                <th className="border-b border-neutral-800 px-3 py-2 font-medium">На сайте</th>
                <th className="border-b border-neutral-800 px-3 py-2 font-medium">Приватная</th>
                <th className="border-b border-neutral-800 px-3 py-2 font-medium">Код доступа</th>
              </tr>
            </thead>
            <tbody>
              {boards.map((b) => (
                <tr key={b.id} className="align-top">
                  <td className="border-b border-neutral-800/60 px-3 py-3">
                    <div className="font-semibold text-neutral-100">
                      /{b.slug}
                      {b.is_private ? (
                        <LockIcon className="ml-1 inline h-3.5 w-3.5 text-amber-400" />
                      ) : null}
                    </div>
                    <div className="text-xs text-neutral-500">{b.title}</div>
                    <div className="mt-0.5 text-[11px] text-neutral-600">
                      {formatNumber(b.media_count)}{" "}
                      {plural(b.media_count, ["файл", "файла", "файлов"])}
                    </div>
                  </td>
                  <td className="border-b border-neutral-800/60 px-3 py-3">
                    <Switch
                      checked={b.parse_enabled}
                      label="Парсить"
                      title="Скачивать файлы с этой доски"
                      onChange={() => void patch(b.slug, { parse_enabled: !b.parse_enabled })}
                    />
                  </td>
                  <td className="border-b border-neutral-800/60 px-3 py-3">
                    <Switch
                      checked={b.is_visible}
                      label="Отображать"
                      title="Показывать раздел на сайте"
                      onChange={() => void patch(b.slug, { is_visible: !b.is_visible })}
                    />
                  </td>
                  <td className="border-b border-neutral-800/60 px-3 py-3">
                    <Switch
                      checked={b.is_private}
                      label="По коду"
                      title="Контент доступен только по коду"
                      onChange={() => void patch(b.slug, { is_private: !b.is_private })}
                    />
                  </td>
                  <td className="border-b border-neutral-800/60 px-3 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`text-[11px] ${
                          b.has_access_code ? "text-emerald-400" : "text-neutral-600"
                        }`}
                      >
                        {b.has_access_code ? "код задан" : "код не задан"}
                      </span>
                      <input
                        type="text"
                        value={codes[b.slug] ?? ""}
                        onChange={(e) => setCodes((prev) => ({ ...prev, [b.slug]: e.target.value }))}
                        placeholder="Новый код"
                        className="w-36 rounded-lg border border-neutral-700 bg-neutral-900 px-2.5 py-1.5 text-xs text-neutral-100 outline-none placeholder:text-neutral-600 focus:border-amber-500"
                      />
                      <button
                        type="button"
                        disabled={busyKey === b.slug || !(codes[b.slug] ?? "").trim()}
                        onClick={() => void setCode(b.slug)}
                        className="btn-ghost px-2.5 py-1.5 text-xs"
                      >
                        {busyKey === b.slug ? <SpinnerIcon className="h-3.5 w-3.5" /> : "Установить"}
                      </button>
                      {b.has_access_code ? (
                        <button
                          type="button"
                          disabled={busyKey === b.slug}
                          onClick={() => void patch(b.slug, { access_code: "" })}
                          className="px-2 py-1.5 text-xs text-neutral-500 transition-colors hover:text-red-400"
                        >
                          Сбросить
                        </button>
                      ) : null}
                    </div>
                    {rowError[b.slug] ? (
                      <div className="mt-1 text-xs text-red-400">{rowError[b.slug]}</div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
