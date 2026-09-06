"use client";

import Link from "next/link";
import { useState } from "react";

import {
  ChevronDownIcon,
  ChevronUpIcon,
  LockIcon,
  PencilIcon,
  PlusIcon,
  SpinnerIcon,
  TrashIcon,
} from "@/components/icons";
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
      className={`inline-flex shrink-0 items-center gap-2 rounded border px-2.5 py-1.5 text-xs font-medium transition-colors ${
        checked
          ? "border-accent-primary/50 bg-accent-primary/15 text-accent-primary"
          : "border-line bg-ink-tertiary text-text-secondary hover:text-text-primary"
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
  onMove,
  onRename,
  onDelete,
}: {
  boards: AdminBoard[] | null;
  loading: boolean;
  busyKey: string | null;
  codes: Record<string, string>;
  rowError: Record<string, string>;
  onSetCodes: (fn: (prev: Record<string, string>) => Record<string, string>) => void;
  onPatch: (slug: string, body: Record<string, unknown>) => Promise<void>;
  onSetCode: (slug: string) => Promise<void>;
  onMove: (slug: string, dir: -1 | 1) => Promise<void>;
  onRename: (slug: string, title: string) => Promise<void>;
  onDelete: (slug: string) => Promise<void>;
}) {
  if (loading && !boards) {
    return <p className="py-10 text-center text-sm text-text-secondary">Загружаем…</p>;
  }
  if (!boards || boards.length === 0) {
    return (
      <p className="py-10 text-center text-sm text-text-secondary">
        Разделов нет. Добавьте slug вручную выше или откройте «Доски форума».
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {boards.map((b, idx) => (
        <BoardRow
          key={b.id}
          board={b}
          position={idx + 1}
          total={boards.length}
          busyKey={busyKey}
          codes={codes}
          rowError={rowError}
          onSetCodes={onSetCodes}
          onPatch={onPatch}
          onSetCode={onSetCode}
          onMove={onMove}
          onRename={onRename}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}
function BoardRow({
  board,
  position,
  total,
  busyKey,
  codes,
  rowError,
  onSetCodes,
  onPatch,
  onSetCode,
  onMove,
  onRename,
  onDelete,
}: {
  board: AdminBoard;
  position: number;
  total: number;
  busyKey: string | null;
  codes: Record<string, string>;
  rowError: Record<string, string>;
  onSetCodes: (fn: (prev: Record<string, string>) => Record<string, string>) => void;
  onPatch: (slug: string, body: Record<string, unknown>) => Promise<void>;
  onSetCode: (slug: string) => Promise<void>;
  onMove: (slug: string, dir: -1 | 1) => Promise<void>;
  onRename: (slug: string, title: string) => Promise<void>;
  onDelete: (slug: string) => Promise<void>;
}) {
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState(board.title);

  async function saveTitle() {
    const title = titleDraft.trim();
    if (title && title !== board.title) await onRename(board.slug, title);
    setEditingTitle(false);
  }

  return (
    <div className="rounded border border-line bg-ink-secondary p-4">
      {/* Шапка: позиция + название + статусы + управление */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded px-1.5 py-0.5 font-mono text-[11px] ${
                board.parse_enabled
                  ? "bg-accent-primary/15 text-accent-primary"
                  : "bg-ink-tertiary text-text-secondary"
              }`}
              title="Позиция в очереди парсинга"
            >
              #{position}
            </span>
            <Link
              href={`/admin/boards/${board.slug}`}
              className="text-base font-semibold text-text-primary transition-colors hover:text-accent-primary"
              title="Открыть треды раздела"
            >
              /{board.slug}
            </Link>
            {board.is_private ? <LockIcon className="h-3.5 w-3.5 text-accent-warning" /> : null}

            {editingTitle ? (
              <span className="inline-flex items-center gap-1">
                <input
                  autoFocus
                  value={titleDraft}
                  onChange={(e) => setTitleDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void saveTitle();
                    if (e.key === "Escape") setEditingTitle(false);
                  }}
                  className="w-48 rounded border border-line bg-ink-secondary px-2 py-1 text-sm text-text-primary outline-none focus:border-accent-primary"
                />
                <button type="button" onClick={() => void saveTitle()} className="btn-ghost px-2 py-1 text-xs">
                  ОК
                </button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setTitleDraft(board.title);
                  setEditingTitle(true);
                }}
                className="inline-flex max-w-56 items-center gap-1 truncate rounded px-1 text-sm text-text-secondary transition-colors hover:text-accent-primary"
                title="Изменить название раздела"
              >
                <span className="truncate">{board.title || "(название)"}</span>
                <PencilIcon className="h-3 w-3 shrink-0 opacity-60" />
              </button>
            )}
          </div>
          <div className="mt-1 text-xs text-text-secondary">
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
          <span className="inline-flex items-center gap-1 rounded border border-line bg-ink-secondary px-1 py-1">
            <button
              type="button"
              disabled={position <= 1}
              onClick={() => void onMove(board.slug, -1)}
              title="Выше в очереди парсинга"
              className="rounded px-1 text-text-secondary transition-colors hover:text-accent-primary disabled:opacity-30"
            >
              <ChevronUpIcon className="h-4 w-4" />
            </button>
            <button
              type="button"
              disabled={position >= total}
              onClick={() => void onMove(board.slug, 1)}
              title="Ниже в очереди парсинга"
              className="rounded px-1 text-text-secondary transition-colors hover:text-accent-primary disabled:opacity-30"
            >
              <ChevronDownIcon className="h-4 w-4" />
            </button>
          </span>
          <button
            type="button"
            disabled={busyKey === board.slug}
            onClick={() => {
              const count = board.media_total;
              const msg =
                count > 0
                  ? `Удалить раздел /${board.slug} и ${formatNumber(count)} файлов из хранилища?`
                  : `Удалить раздел /${board.slug}?`;
              if (window.confirm(msg)) void onDelete(board.slug);
            }}
            title="Удалить раздел (БД + файлы в B2)"
            className="rounded border border-accent-danger/30 px-1.5 py-1 text-text-secondary transition-colors hover:border-accent-danger/60 hover:text-accent-danger"
          >
            <TrashIcon className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Статистика загрузки */}
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-text-secondary">
        <span>
          В БД: <b className="text-text-primary">{formatNumber(board.media_total)}</b>
        </span>
        <span>
          В B2: <b className="text-accent-secondary">{formatNumber(board.media_in_b2)}</b>
        </span>
        <span>
          Скачано: <b className="text-text-primary">{formatNumber(board.media_downloaded)}</b>
        </span>
        <span>
          Пропущено: <b className="text-accent-danger">{formatNumber(board.media_missing)}</b>
        </span>
        <span>В каталоге: {formatNumber(board.files_in_catalog)}</span>
        <span>Видимых: {formatNumber(board.media_count)}</span>
      </div>

      {/* Код доступа: задаётся заранее, до включения «По коду» */}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
        <span className={`text-xs ${board.has_access_code ? "text-accent-secondary" : "text-text-muted"}`}>
            {board.has_access_code ? "код задан" : "код не задан"}
          </span>
          <input
            type="text"
            value={codes[board.slug] ?? ""}
            onChange={(e) => onSetCodes((prev) => ({ ...prev, [board.slug]: e.target.value }))}
            placeholder="Новый код"
            className="w-40 rounded border border-line bg-ink-secondary px-2.5 py-1.5 text-xs text-text-primary outline-none placeholder:text-text-muted focus:border-accent-primary"
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
              className="px-2 py-1.5 text-xs text-text-secondary transition-colors hover:text-accent-danger"
            >
              Сбросить
            </button>
          ) : null}
        </div>
      {rowError[board.slug] ? (
        <div className="mt-2 text-xs text-accent-danger">{rowError[board.slug]}</div>
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
  onAdd: (slug: string, name?: string | null) => Promise<void>;
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
          className="w-72 rounded border border-line bg-ink-secondary px-3 py-2 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-accent-primary"
        />
        <button type="button" onClick={onRefresh} disabled={loading} className="btn-ghost">
          {loading ? <SpinnerIcon className="h-4 w-4" /> : null}
          Обновить список
        </button>
        {forum ? (
          <span className="text-xs text-text-secondary">
            Всего досок на форуме: {formatNumber(forum.length)} · показано:{" "}
            {formatNumber(filtered.length)}
          </span>
        ) : null}
      </div>

      {loading && !forum ? (
        <p className="py-8 text-center text-sm text-text-secondary">Сканируем доски форума…</p>
      ) : forum === null ? (
        <p className="py-8 text-center text-sm text-text-secondary">
          Список досок форума недоступен (сервер не ответил).
        </p>
      ) : filtered.length === 0 ? (
        <p className="py-8 text-center text-sm text-text-secondary">Ничего не найдено.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {filtered.map((f) => (
            <div
              key={f.slug}
              className="flex flex-wrap items-center justify-between gap-2 rounded border border-line bg-ink-secondary px-3 py-2"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-text-primary">/{f.slug}</span>
                  {f.name ? <span className="truncate text-sm text-text-secondary">{f.name}</span> : null}
                  {f.category ? (
                    <span className="rounded bg-ink-tertiary px-1.5 py-0.5 text-[10px] text-text-secondary">
                      {f.category}
                    </span>
                  ) : null}
                  {f.in_db ? (
                    <span className="rounded bg-accent-secondary/10 px-1.5 py-0.5 text-[10px] text-accent-secondary">
                      в системе
                    </span>
                  ) : (
                    <span className="rounded bg-ink-tertiary px-1.5 py-0.5 text-[10px] text-text-secondary">
                      не добавлена
                    </span>
                  )}
                </div>
                <div className="mt-0.5 text-xs text-text-secondary">
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
                <Link href={`/admin/boards/${f.slug}`} className="text-xs text-accent-primary hover:text-amber-200">
                  Управлять →
                </Link>
              ) : (
                <button
                  type="button"
                  onClick={() => void onAdd(f.slug, f.name)}
                  className="btn-ghost px-2.5 py-1.5 text-xs"
                >
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


