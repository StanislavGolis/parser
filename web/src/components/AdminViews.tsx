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
import AdminBoardThreads from "@/components/AdminBoardThreads";
import { Switch } from "@/components/Switch";
import { formatNumber } from "@/lib/format";
import type { AdminBoard, ParserStatus, SourceBoard } from "@/lib/types";

// Переключатель Switch вынесен в @/components/Switch (кругового импорта нет).

export function BoardsTable({
  boards,
  loading,
  parserStatus,
  busyKey,
  rowError,
  onPatch,
  onMove,
  onRename,
  onDelete,
}: {
  boards: AdminBoard[] | null;
  loading: boolean;
  parserStatus?: ParserStatus | null;
  busyKey: string | null;
  rowError: Record<string, string>;
  onPatch: (slug: string, body: Record<string, unknown>) => Promise<void>;
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
        Разделов нет. Добавьте slug вручную выше или откройте список разделов источника.
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
          parserStatus={parserStatus}
          busyKey={busyKey}
          rowError={rowError}
          onPatch={onPatch}
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
  parserStatus,
  busyKey,
  rowError,
  onPatch,
  onMove,
  onRename,
  onDelete,
}: {
  board: AdminBoard;
  position: number;
  total: number;
  parserStatus?: ParserStatus | null;
  busyKey: string | null;
  rowError: Record<string, string>;
  onPatch: (slug: string, body: Record<string, unknown>) => Promise<void>;
  onMove: (slug: string, dir: -1 | 1) => Promise<void>;
  onRename: (slug: string, title: string) => Promise<void>;
  onDelete: (slug: string) => Promise<void>;
}) {
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState(board.title);
  const [showThreads, setShowThreads] = useState(false);

  // Прогресс парсера по этой доске (если сейчас парсится именно она)
  const parser = parserStatus ?? null;
  const progress =
    parser?.alive && parser.current_board === board.slug ? parser.progress : null;
  const filesDone = progress?.files_done ?? 0;
  const filesTotal = progress?.files_total ?? 0;
  // «Завис» — это когда процесс молчит (нет живости), а не когда давно не было
  // новой порции прогресса: большой файл может качаться минутами.
  const stalled = Boolean(progress && parser && !parser.alive);
  const percent =
    progress?.phase === "files" && filesTotal > 0
      ? Math.min(100, Math.round((filesDone / filesTotal) * 100))
      : progress?.phase === "catalog"
        ? 10
        : 0;

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
              href={`/board/${board.slug}`}
              className="text-base font-semibold text-text-primary transition-colors hover:text-accent-primary"
              title="Открыть раздел на сайте"
            >
              /{board.slug}
            </Link>
            {board.is_premium ? <LockIcon className="h-3.5 w-3.5 text-accent-warning" /> : null}
            {board.catalog_error ? (
              <span
                className="badge border-accent-danger text-accent-danger"
                title={`${board.catalog_error}. Раздел удалён с форума или slug неверный — парсить его нельзя.`}
              >
                каталог недоступен
              </span>
            ) : null}

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
            парсим: {formatNumber(board.threads_parsing)} ·{" "}
            {formatNumber(board.views_total)} просмотров · {formatNumber(board.downloads_total)}{" "}
            скачиваний
            {board.last_scan ? (
              <> · скан: {new Date(board.last_scan + "Z").toLocaleString("ru-RU")}</>
            ) : null}
            {board.threads_pending > 0 ? (
              <span className="badge badge-ok ml-2" title="Треды стоят в очереди на докачку (фаза B)">
                в очереди: {formatNumber(board.threads_pending)}
              </span>
            ) : null}
            {board.threads_dead > 0 ? (
              <span
                className="badge border-accent-danger text-accent-danger ml-2"
                title="Треды выпали из каталога форума — смотрите чип «Мёртвые» в списке тредов"
              >
                мёртвых: {formatNumber(board.threads_dead)}
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setShowThreads((v) => !v)}
            className="btn-ghost px-2.5 py-1.5 text-xs"
            title="Показать/скрыть управление тредами"
          >
            Треды {showThreads ? "▴" : "▾"}
            <span className="ml-1 text-text-muted">
              {formatNumber(board.threads_parsing)}/{formatNumber(board.threads_active)}
            </span>
          </button>
          <Switch
            checked={board.parse_enabled}
            label="Парсить"
            title="Скачивать файлы с этой доски"
            onChange={() => void onPatch(board.slug, { parse_enabled: !board.parse_enabled })}
          />
          <Switch
            checked={board.is_visible}
            label={board.is_visible ? "published" : "unpublished"}
            title="Показывать раздел на сайте (published/unpublished)"
            onChange={() => void onPatch(board.slug, { is_visible: !board.is_visible })}
          />
          <Switch
            checked={board.is_premium}
            label={board.is_premium ? "PREMIUM" : "FREE"}
            title="Премиум-доступ: превью размыты, полные файлы — по подписке"
            onChange={() => void onPatch(board.slug, { is_premium: !board.is_premium })}
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
            title="Удалить раздел (БД + файлы в S3)"
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
          В S3: <b className="text-accent-secondary">{formatNumber(board.media_in_s3)}</b>
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

      {/* Премиум-доступ: включается переключателем FREE/PREMIUM в шапке */}
      {board.is_premium ? (
        <div className="mt-3 border-t border-line pt-3 text-[11px] text-accent-warning">
          Премиум-доступ включён: превью всех файлов размыты, полные версии — только по подписке.
        </div>
      ) : null}
      {progress ? (
        <div className="mt-3 rounded border border-line bg-ink-tertiary/40 px-3 py-2">
          <div className="flex items-center justify-between text-[11px] text-text-secondary">
            <span>
              {progress.phase === "files"
                ? `парсим тред №${progress.thread_id}: ${formatNumber(filesDone)}/${formatNumber(filesTotal)} файлов`
                : "сканируем каталог доски…"}
            </span>
            <span className={stalled ? "text-accent-danger" : "text-text-muted"}>
              {stalled
                ? `нет связи с парсером${
                    parser?.stall_seconds != null ? ` · ${parser.stall_seconds} с` : ""
                  }`
                : parser?.stall_seconds != null
                  ? `обновлено ${parser.stall_seconds} с назад`
                  : ""}
            </span>
          </div>
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded bg-ink-tertiary">
            <div
              className={`h-full transition-all ${stalled ? "bg-accent-danger" : "bg-accent-primary"}`}
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>
      ) : null}

      {showThreads ? (
        <div className="mt-3 border-t border-line pt-3">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-text-secondary">
            <span>Новые треды:</span>
            <Switch
              checked={board.parse_mode === "all"}
              label={board.parse_mode === "all" ? "парсить" : "не парсить"}
              title="По умолчанию для новых тредов при сканировании каталога"
              onChange={() =>
                void onPatch(board.slug, {
                  parse_mode: board.parse_mode === "all" ? "selected" : "all",
                })
              }
            />
          </div>
          <AdminBoardThreads slug={board.slug} parserStatus={parserStatus} boardPremium={board.is_premium} />
        </div>
      ) : null}

      {rowError[board.slug] ? (
        <div className="mt-2 text-xs text-accent-danger">{rowError[board.slug]}</div>
      ) : null}
    </div>
  );
}

export function CatalogTab({
  items,
  loading,
  query,
  onQuery,
  onRefresh,
  onAdd,
  onRemove,
  addError,
  hintLabel = "в источнике",
}: {
  items: SourceBoard[] | null;
  loading: boolean;
  query: string;
  onQuery: (v: string) => void;
  onRefresh: () => void;
  onAdd: (slug: string, name?: string | null, force?: boolean) => Promise<void>;
  onRemove: (slug: string) => Promise<void>;
  /** Ошибки добавления по слагам: сообщение + можно ли добавить принудительно. */
  addError?: Record<string, { message: string; canForce: boolean }>;
  /** Подпись счётчика источника: у 2ch это треды на форуме, у сайта — записей. */
  hintLabel?: string;
}) {
  const q = query.trim().toLowerCase();
  const filtered = (items ?? []).filter(
    (f) =>
      !q ||
      f.slug.includes(q) ||
      (f.name ?? "").toLowerCase().includes(q) ||
      (f.group ?? "").toLowerCase().includes(q),
  );

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder="Поиск по slug / названию / рубрике"
          className="w-72 rounded border border-line bg-ink-secondary px-3 py-2 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-accent-primary"
        />
        <button type="button" onClick={onRefresh} disabled={loading} className="btn-ghost">
          {loading ? <SpinnerIcon className="h-4 w-4" /> : null}
          Обновить список
        </button>
        {items ? (
          <span className="text-xs text-text-secondary">
            Всего разделов: {formatNumber(items.length)} · показано:{" "}
            {formatNumber(filtered.length)}
          </span>
        ) : null}
      </div>

      {loading && !items ? (
        <p className="py-8 text-center text-sm text-text-secondary">Запрашиваем разделы у источника…</p>
      ) : items === null ? (
        <p className="py-8 text-center text-sm text-text-secondary">
          Список разделов недоступен (сервер или источник не ответил).
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
                  {f.group ? (
                    <span className="rounded bg-ink-tertiary px-1.5 py-0.5 text-[10px] text-text-secondary">
                      {f.group}
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
                  {f.hint > 0 ? `${hintLabel}: ${formatNumber(f.hint)} «тредов»` : null}
                  {f.in_db ? (
                    <>
                      {" "}
                      · у нас: {formatNumber(f.media_total)} файлов (в S3:{" "}
                      {formatNumber(f.media_in_s3)})
                    </>
                  ) : null}
                </div>
              </div>
              {f.in_db ? (
                <button
                  type="button"
                  onClick={() => {
                    if (
                      window.confirm(
                        `Убрать раздел /${f.slug} из «Мои разделы»? Данные раздела (файлы и треды) будут удалены.`,
                      )
                    ) {
                      void onRemove(f.slug);
                    }
                  }}
                  className="rounded border border-accent-danger/30 px-2.5 py-1.5 text-xs text-text-secondary transition-colors hover:border-accent-danger/60 hover:text-accent-danger"
                >
                  Убрать
                </button>
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
              {addError?.[f.slug] ? (
                <div className="w-full rounded border border-accent-danger/30 bg-red-500/5 px-2 py-1.5 text-xs text-accent-danger">
                  <div>{addError[f.slug].message}</div>
                  {addError[f.slug].canForce ? (
                    <button
                      type="button"
                      onClick={() => void onAdd(f.slug, f.name, true)}
                      className="mt-1 rounded border border-line px-2 py-1 text-[11px] text-text-secondary transition-colors hover:text-text-primary"
                      title="Добавить раздел в список, даже если источник сейчас не отдаёт его список: парситься он не будет, пока раздел не подтвердится каталогом"
                    >
                      Добавить всё равно
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


