"use client";

import Link from "next/link";

import { LockIcon, PlusIcon, SpinnerIcon } from "@/components/icons";
import { formatNumber } from "@/lib/format";
import type { AdminBoard, ForumBoard } from "@/lib/types";

export function Switch({
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
      <span className={`h-2 w-2 rounded-full ${checked ? "bg-amber-400" : "bg-neutral-600"}`} />
      {label}
    </button>
  );
}

export function BoardsTable({
  boards,
  loading,
  busyKey,
  codes,
  rowError,
  onSetCodes,
  onPatch,
  onSetCode,
}: {
  boards: AdminBoard[] | null;
  loading: boolean;
  busyKey: string | null;
  codes: Record<string, string>;
  rowError: Record<string, string>;
  onSetCodes: (fn: (prev: Record<string, string>) => Record<string, string>) => void;
  onPatch: (slug: string, body: Record<string, unknown>) => Promise<void>;
  onSetCode: (slug: string) => Promise<void>;
}) {
  if (loading && !boards) {
    return <p className="py-10 text-center text-sm text-neutral-400">Загружаем…</p>;
  }
  if (!boards || boards.length === 0) {
    return (
      <p className="py-10 text-center text-sm text-neutral-500">
        Разделов нет. Добавьте slug вручную выше или откройте «Доски форума».
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {boards.map((b) => (
        <BoardRow
          key={b.id}
          board={b}
          busyKey={busyKey}
          codes={codes}
          rowError={rowError}
          onSetCodes={onSetCodes}
          onPatch={onPatch}
          onSetCode={onSetCode}
        />
      ))}
    </div>
  );
}
function BoardRow({
  board,
  busyKey,
  codes,
  rowError,
  onSetCodes,
  onPatch,
  onSetCode,
}: {
  board: AdminBoard;
  busyKey: string | null;
  codes: Record<string, string>;
  rowError: Record<string, string>;
  onSetCodes: (fn: (prev: Record<string, string>) => Record<string, string>) => void;
  onPatch: (slug: string, body: Record<string, unknown>) => Promise<void>;
  onSetCode: (slug: string) => Promise<void>;
}) {
  return (
    <div className="rounded-2xl border border-neutral-800 bg-neutral-900/40 p-4">
      {/* Шапка: название + статусы */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/admin/boards/${board.slug}`}
              className="text-base font-semibold text-neutral-100 transition-colors hover:text-amber-300"
              title="Открыть треды раздела"
            >
              /{board.slug}
            </Link>
            {board.is_private ? <LockIcon className="h-3.5 w-3.5 text-amber-400" /> : null}
            <span className="truncate text-sm text-neutral-500">{board.title}</span>
          </div>
          <div className="mt-1 text-xs text-neutral-500">
            {formatNumber(board.media_total)} файлов · {formatNumber(board.threads_active)} тредов ·{" "}
            {formatNumber(board.views_total)} просмотров · {formatNumber(board.downloads_total)}{" "}
            скачиваний
            {board.last_scan ? (
              <> · скан: {new Date(board.last_scan + "Z").toLocaleString("ru-RU")}</>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Switch
            checked={board.parse_enabled}
            label="Парсить"
            title="Скачивать файлы с этой доски"
            onChange={() => void onPatch(board.slug, { parse_enabled: !board.parse_enabled })}
          />
          <Switch
            checked={board.is_visible}
            label="На сайте"
            title="Показывать раздел на сайте"
            onChange={() => void onPatch(board.slug, { is_visible: !board.is_visible })}
          />
          <Switch
            checked={board.is_private}
            label="По коду"
            title="Контент доступен только по коду"
            onChange={() => void onPatch(board.slug, { is_private: !board.is_private })}
          />
        </div>
      </div>

      {/* Статистика загрузки */}
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-neutral-400">
        <span>
          В БД: <b className="text-neutral-200">{formatNumber(board.media_total)}</b>
        </span>
        <span>
          В B2: <b className="text-emerald-400">{formatNumber(board.media_in_b2)}</b>
        </span>
        <span>
          Скачано: <b className="text-neutral-200">{formatNumber(board.media_downloaded)}</b>
        </span>
        <span>
          Пропущено: <b className="text-red-400">{formatNumber(board.media_missing)}</b>
        </span>
        <span>В каталоге: {formatNumber(board.files_in_catalog)}</span>
        <span>Видимых: {formatNumber(board.media_count)}</span>
      </div>

      {/* Код доступа */}

      {board.is_private || board.has_access_code ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-neutral-800/70 pt-3">
          <span className={`text-xs ${board.has_access_code ? "text-emerald-400" : "text-neutral-600"}`}>
            {board.has_access_code ? "код задан" : "код не задан"}
          </span>
          <input
            type="text"
            value={codes[board.slug] ?? ""}
            onChange={(e) => onSetCodes((prev) => ({ ...prev, [board.slug]: e.target.value }))}
            placeholder="Новый код"
            className="w-40 rounded-lg border border-neutral-700 bg-neutral-900 px-2.5 py-1.5 text-xs text-neutral-100 outline-none placeholder:text-neutral-600 focus:border-amber-500"
          />
          <button
            type="button"
            disabled={busyKey === board.slug || !(codes[board.slug] ?? "").trim()}
            onClick={() => void onSetCode(board.slug)}
            className="btn-ghost px-2.5 py-1.5 text-xs"
          >
            {busyKey === board.slug ? <SpinnerIcon className="h-3.5 w-3.5" /> : "Установить"}
          </button>
          {board.has_access_code ? (
            <button
              type="button"
              disabled={busyKey === board.slug}
              onClick={() => void onPatch(board.slug, { access_code: "" })}
              className="px-2 py-1.5 text-xs text-neutral-500 transition-colors hover:text-red-400"
            >
              Сбросить
            </button>
          ) : null}
        </div>
      ) : null}
      {rowError[board.slug] ? (
        <div className="mt-2 text-xs text-red-400">{rowError[board.slug]}</div>
      ) : null}
    </div>
  );
}

export function ForumTab({
  forum,
  loading,
  query,
  onQuery,
  onRefresh,
  onAdd,
}: {
  forum: ForumBoard[] | null;
  loading: boolean;
  query: string;
  onQuery: (v: string) => void;
  onRefresh: () => void;
  onAdd: (slug: string) => Promise<void>;
}) {
  const q = query.trim().toLowerCase();
  const filtered = (forum ?? []).filter(
    (f) =>
      !q ||
      f.slug.includes(q) ||
      (f.name ?? "").toLowerCase().includes(q) ||
      (f.category ?? "").toLowerCase().includes(q),
  );

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder="Поиск по slug / названию / категории"
          className="w-72 rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 outline-none transition-colors placeholder:text-neutral-600 focus:border-amber-500"
        />
        <button type="button" onClick={onRefresh} disabled={loading} className="btn-ghost">
          {loading ? <SpinnerIcon className="h-4 w-4" /> : null}
          Обновить список
        </button>
        {forum ? (
          <span className="text-xs text-neutral-500">
            Всего досок на форуме: {formatNumber(forum.length)} · показано:{" "}
            {formatNumber(filtered.length)}
          </span>
        ) : null}
      </div>

      {loading && !forum ? (
        <p className="py-8 text-center text-sm text-neutral-400">Сканируем доски форума…</p>
      ) : forum === null ? (
        <p className="py-8 text-center text-sm text-neutral-500">
          Список досок форума недоступен (сервер не ответил).
        </p>
      ) : filtered.length === 0 ? (
        <p className="py-8 text-center text-sm text-neutral-500">Ничего не найдено.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {filtered.map((f) => (
            <div
              key={f.slug}
              className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-neutral-800 bg-neutral-900/40 px-3 py-2"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-neutral-100">/{f.slug}</span>
                  {f.name ? <span className="truncate text-sm text-neutral-400">{f.name}</span> : null}
                  {f.category ? (
                    <span className="rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-500">
                      {f.category}
                    </span>
                  ) : null}
                  {f.in_db ? (
                    <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-400">
                      в системе
                    </span>
                  ) : (
                    <span className="rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-500">
                      не добавлена
                    </span>
                  )}
                </div>
                <div className="mt-0.5 text-xs text-neutral-500">
                  на форуме: {formatNumber(f.threads_on_forum)} тредов
                  {f.in_db ? (
                    <>
                      {" "}
                      · у нас: {formatNumber(f.media_total)} файлов (в B2:{" "}
                      {formatNumber(f.media_in_b2)})
                    </>
                  ) : null}
                </div>
              </div>
              {f.in_db ? (
                <Link href={`/admin/boards/${f.slug}`} className="text-xs text-amber-300 hover:text-amber-200">
                  Управлять →
                </Link>
              ) : (
                <button type="button" onClick={() => void onAdd(f.slug)} className="btn-ghost px-2.5 py-1.5 text-xs">
                  <PlusIcon className="h-3.5 w-3.5" />
                  Добавить
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


