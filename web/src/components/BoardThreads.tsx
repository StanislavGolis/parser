"use client";

import { useCallback, useEffect, useState } from "react";

import Lightbox from "@/components/Lightbox";
import {
  CloseIcon,
  FilmIcon,
  HistoryIcon,
  ImageIcon,
  LockIcon,
  PlayIcon,
  SpinnerIcon,
  StarIcon,
} from "@/components/icons";
import When from "@/components/When";
import { apiGet } from "@/lib/api";
import { mediaUrl } from "@/lib/env";
import { thumbSrc, premiumState } from "@/lib/media";
import { formatDuration, formatNumber, formatRelative } from "@/lib/format";
import { clearResume, getResume, readResumes, resumeIndex } from "@/lib/resume";
import type { ResumeMap, ResumePoint } from "@/lib/resume";
import type { BoardThread, MediaItem, MediaList, ThreadList } from "@/lib/types";

const PER_PAGE = 15;
const MAX_PREVIEW = 8;
/** Порция файлов треда в лайтбоксе: 300 — максимум, который отдаёт API. */
const THREAD_PAGE_SIZE = 300;

interface BoardThreadsProps {
  slug: string;
  initial: ThreadList;
  /** Порядок тредов из URL (`?sort=`): new | files | posts | views. */
  sort?: string;
  /** Тред из ссылки (`?thread=…`): открываем его сразу — из ленты, меток, топа. */
  initialThreadId?: number | null;
}

/** Варианты сортировки тредов внутри раздела. */
const SORTS: Array<{ value: string; label: string; title: string }> = [
  {
    value: "new",
    label: "свежие",
    title: "Сначала треды, в которые позже всех добавлялись файлы",
  },
  {
    value: "files",
    label: "по файлам",
    title: "Сначала треды с большим числом файлов в архиве",
  },
];

/**
 * Доска в виде «список тредов → их файлы».
 * Кнопка открытия треда догружает все файлы треда и открывает Lightbox.
 */
export default function BoardThreads({
  slug,
  initial,
  sort: initialSort = "new",
  initialThreadId = null,
}: BoardThreadsProps) {
  const [sort, setSort] = useState(initialSort);
  const [threads, setThreads] = useState<BoardThread[]>(initial.items);
  const [page, setPage] = useState(initial.page);
  const [total, setTotal] = useState(initial.total);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Lightbox с файлами конкретного треда. Порция — 300 файлов (максимум API),
  // но в треде их бывает больше: держим `total` (полный размер) и `page`, чтобы
  // догружать следующие порции и не путать «размер треда» с «размером порции» —
  // из-за этой путаницы «+N новых в конце» показывало лишнее (в треде из 882
  // файлов выходило «+582»).
  const [lightbox, setLightbox] = useState<{
    items: MediaItem[];
    index: number;
    threadId: number;
    total: number;
    page: number;
  } | null>(null);
  const [lightboxBusy, setLightboxBusy] = useState(false);
  const [openingThread, setOpeningThread] = useState<number | null>(null);

  // Точки возврата «продолжить просмотр» (localStorage). Читаем после
  // монтирования: на сервере хранилища нет, иначе SSR и первый рендер разошлись бы.
  const [resumes, setResumes] = useState<ResumeMap>({});
  useEffect(() => {
    setResumes(readResumes());
  }, []);

  const hasMore = threads.length < total;

  const loadMore = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiGet<ThreadList>(
        `/api/v1/boards/${encodeURIComponent(slug)}/threads?page=${page + 1}&per_page=${PER_PAGE}&sort=${sort}`,
      );
      setThreads((prev) => {
        const seen = new Set(prev.map((t) => t.thread_id));
        const fresh = data.items.filter((t) => !seen.has(t.thread_id));
        return fresh.length > 0 ? [...prev, ...fresh] : prev;
      });
      setPage(data.page);
      setTotal(data.total);
    } catch {
      setError("Не удалось загрузить ещё треды. Попробуйте позже.");
    } finally {
      setLoading(false);
    }
  }, [slug, page, loading, sort]);

  /**
   * Смена порядка: грузим первую страницу заново и меняем адрес без перезагрузки,
   * чтобы ссылкой можно было поделиться (`/board/gg?sort=files`).
   */
  const changeSort = useCallback(
    async (next: string) => {
      if (next === sort) return;
      setSort(next);
      setLoading(true);
      setError(null);
      try {
        const data = await apiGet<ThreadList>(
          `/api/v1/boards/${encodeURIComponent(slug)}/threads?page=1&per_page=${PER_PAGE}&sort=${next}`,
        );
        setThreads(data.items);
        setPage(data.page);
        setTotal(data.total);
        if (typeof window !== "undefined") {
          const url = new URL(window.location.href);
          if (next === "new") url.searchParams.delete("sort");
          else url.searchParams.set("sort", next);
          window.history.replaceState(null, "", url.toString());
        }
      } catch {
        setError("Не удалось изменить порядок тредов. Попробуйте позже.");
      } finally {
        setLoading(false);
      }
    },
    [slug, sort],
  );

  async function fetchThreadMedia(threadId: number, page = 1): Promise<MediaList> {
    const q = new URLSearchParams({
      thread: String(threadId),
      per_page: String(THREAD_PAGE_SIZE),
      sort: "new",
      page: String(page),
    });
    return apiGet<MediaList>(`/api/v1/boards/${encodeURIComponent(slug)}/media?${q}`);
  }

  /** Догружает следующую порцию файлов уже открытого треда (кнопка/листание). */
  const loadMoreLightbox = useCallback(async () => {
    const current = lightbox;
    if (!current || lightboxBusy) return;
    if (current.items.length >= current.total) return;
    setLightboxBusy(true);
    try {
      const next = await fetchThreadMedia(current.threadId, current.page + 1);
      setLightbox((prev) => {
        if (!prev || next.items.length === 0) return prev;
        const seen = new Set(prev.items.map((m) => m.id));
        return {
          ...prev,
          items: [...prev.items, ...next.items.filter((m) => !seen.has(m.id))],
          page: next.page,
        };
      });
    } catch {
      setError("Не удалось догрузить файлы треда. Попробуйте позже.");
    } finally {
      setLightboxBusy(false);
    }
  }, [lightbox, lightboxBusy, slug]);

  /**
   * Открывает файлы треда в лайтбоксе. Без явного индекса продолжаем с того
   * файла, который зритель смотрел последним: файл ищем по id, сохранённая
   * позиция — только запасной вариант (см. lib/resume).
   *
   * Точка возврата может лежать дальше первой порции (в треде бывает 800+ файлов),
   * поэтому порции догружаются, пока не дойдём до нужного места.
   */
  async function openThread(
    threadId: number,
    opts?: { startIndex?: number; mediaId?: number },
  ) {
    setOpeningThread(threadId);
    try {
      const first = await fetchThreadMedia(threadId, 1);
      if (first.items.length === 0) return;

      const point = getResume(threadId);
      // Что ищем в порциях: конкретный файл (клик по превью) или точку возврата
      const wantId = opts?.mediaId ?? (opts?.startIndex === undefined ? point?.id : undefined);
      let items = first.items;
      let page = first.page;
      // Нужный файл может лежать во второй/третьей порции (в треде бывает 800+
      // файлов при порции 300): догружаем, пока он не появится.
      if (wantId && !items.some((m) => m.id === wantId)) {
        while (items.length < first.total && page < 20) {
          const next = await fetchThreadMedia(threadId, page + 1);
          if (next.items.length === 0) break;
          const seen = new Set(items.map((m) => m.id));
          items = [...items, ...next.items.filter((m) => !seen.has(m.id))];
          page = next.page;
          if (items.some((m) => m.id === wantId)) break;
        }
      }

      // Приоритет: явный индекс → конкретный файл → точка возврата
      const byId = wantId ? items.findIndex((m) => m.id === wantId) : -1;
      const index =
        opts?.startIndex ?? (byId >= 0 ? byId : resumeIndex(point, items));
      setLightbox({
        items,
        index: Math.min(Math.max(index, 0), items.length - 1),
        threadId,
        total: first.total,
        page,
      });
    } catch {
      setError("Не удалось открыть тред. Попробуйте ещё раз.");
    } finally {
      setOpeningThread(null);
    }
  }

  // Ссылка вида `/board/gg?thread=2306409` (из ленты, меток, топа, поиска):
  // сразу открываем этот тред в лайтбоксе — зритель попадает точно в место,
  // которое указано на карточке медиа.
  useEffect(() => {
    if (!initialThreadId) return;
    void openThread(initialThreadId);
    // openThread объявлена ниже как function-декларация (поднимается), зависимостей нет
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialThreadId]);

  /** Убирает `?thread=` из адреса: после закрытия лайтбокса это уже не точка входа. */
  const dropThreadParam = useCallback(() => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (!url.searchParams.has("thread")) return;
    url.searchParams.delete("thread");
    window.history.replaceState(null, "", url.toString());
  }, []);

  if (threads.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-neutral-800 py-20 text-center">
        <ImageIcon className="h-10 w-10 text-neutral-700" />
        <p className="font-medium text-neutral-300">В этом разделе пока пусто</p>
        <p className="text-sm text-neutral-500">
          Треды появятся здесь автоматически.
        </p>
      </div>
    );
  }

  return (
    <div>
      {/* Порядок тредов внутри раздела. Выбор попадает в адрес (`?sort=files`),
          поэтому ссылкой можно поделиться, а «назад» возвращает прежний порядок. */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] uppercase tracking-wider text-text-muted">
          порядок:
        </span>
        {SORTS.map((s) => (
          <button
            key={s.value}
            type="button"
            onClick={() => void changeSort(s.value)}
            disabled={loading}
            title={s.title}
            className={`filter-btn font-mono text-[11px] ${
              sort === s.value ? "filter-btn-active" : ""
            }`}
          >
            {s.label}
          </button>
        ))}
        {loading ? <SpinnerIcon className="h-3.5 w-3.5 animate-spin text-text-muted" /> : null}
      </div>

      <div className="flex flex-col gap-4">
        {threads.map((t) => (
          <ThreadCard
            key={t.thread_id}
            slug={slug}
            thread={t}
            opening={openingThread === t.thread_id}
            resume={resumes[`t${t.thread_id}`] ?? null}
            onOpenAll={() => void openThread(t.thread_id, { startIndex: 0 })}
            onOpenAt={(mediaId) => void openThread(t.thread_id, { mediaId })}
            onResume={() => void openThread(t.thread_id)}
            onForget={() => {
              clearResume(t.thread_id);
              setResumes(readResumes());
            }}
          />
        ))}
      </div>

      {hasMore ? (
        <div className="mt-6 flex justify-center">
          <button
            type="button"
            onClick={() => void loadMore()}
            disabled={loading}
            className="btn-small font-mono"
          >
            {loading ? <SpinnerIcon className="h-3.5 w-3.5" /> : null}
            ещё треды · {formatNumber(threads.length)} из {formatNumber(total)}
          </button>
        </div>
      ) : null}
      {error ? <p className="mt-3 text-center text-sm text-red-400">{error}</p> : null}

      {lightbox ? (
        <Lightbox
          items={lightbox.items}
          index={lightbox.index}
          // Полный размер треда для точки возврата и счётчика позиции: в порции
          // максимум 300 файлов, а в треде бывает 800+ (см. loadMoreLightbox)
          resumeThreadId={lightbox.threadId}
          resumeTotal={lightbox.total}
          hasMore={lightbox.items.length < lightbox.total}
          loadingMore={lightboxBusy}
          onLoadMore={() => void loadMoreLightbox()}
          // при закрытии обновляем чипы «продолжить»: точка возврата сдвинулась
          onClose={() => {
            setLightbox(null);
            setResumes(readResumes());
            // `?thread=` больше не нужен: закрыли — значит ссылка отработала
            dropThreadParam();
          }}
          onPrev={() =>
            setLightbox((lb) =>
              lb && lb.items.length > 1
                ? { ...lb, index: (lb.index - 1 + lb.items.length) % lb.items.length }
                : lb,
            )
          }
          onNext={() => {
            // Дошли до последнего загруженного файла — подтягиваем следующую порцию,
            // чтобы зритель мог листать тред дальше (в треде бывает 800+ файлов)
            const lb = lightbox;
            if (lb && lb.index >= lb.items.length - 1 && lb.items.length < lb.total) {
              void loadMoreLightbox();
            }
            setLightbox((cur) =>
              cur && cur.items.length > 1 ? { ...cur, index: (cur.index + 1) % cur.items.length } : cur,
            );
          }}
          onSelect={(i) => setLightbox((lb) => (lb ? { ...lb, index: i } : lb))}
        />
      ) : null}
    </div>
  );
}

/** Карточка треда: шапка + превью файлов; клик открывает Lightbox со всеми файлами. */
function ThreadCard({
  slug,
  thread,
  opening,
  resume,
  onOpenAll,
  onOpenAt,
  onResume,
  onForget,
}: {
  slug: string;
  thread: BoardThread;
  opening: boolean;
  /** Последний просмотренный файл треда (или null — треда нет в истории). */
  resume: ResumePoint | null;
  onOpenAll: () => void;
  /** Клик по превью: открыть тред именно на этом файле. */
  onOpenAt: (mediaId: number) => void;
  onResume: () => void;
  onForget: () => void;
}) {
  const title = thread.subject?.trim() || `Тред #${thread.thread_id}`;
  const preview = thread.preview;
  const visibleCount = thread.media_visible;
  // `thread.files_count` («в каталоге») больше не показываем: это число, которое
  // заявляет сам источник в своём каталоге (у 2ch — из catalog.json), оно бывает
  // устаревшим и меньше фактического, а у сайтов-источников вообще нулевое.
  // Сколько файлов в треде появилось после последнего просмотра. Они всегда
  // «в конце»: список треда идёт по порядку источника (`source_order`), а не по
  // времени скачивания, поэтому новые файлы не сдвигают уже просмотренное.
  //
  // Считаем только по точной точке возврата (`exact`): прежний формат хранил
  // размер загруженной порции (300), и счётчик показывал выдуманные «+582».
  const freshCount =
    resume && resume.exact !== false ? Math.max(0, visibleCount - resume.total) : 0;

  return (
    <article className="overflow-hidden rounded border border-line bg-ink-secondary">
      {/* Шапка треда */}
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-2.5 sm:px-4">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold text-text-primary" title={title}>
            {title}
          </h2>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-text-muted">
            <span>№{thread.thread_id}</span>
            {thread.is_premium ? (
              <span
                className="inline-flex items-center gap-1 rounded-[3px] bg-accent-warning/15 px-1.5 py-0.5 text-accent-warning"
                title={
                  thread.locked
                    ? "Премиум-тред: нужна подписка"
                    : "Премиум-тред: доступен по вашей подписке"
                }
              >
                {thread.locked ? <LockIcon className="h-3 w-3" /> : <StarIcon className="h-3 w-3" />}
                premium
              </span>
            ) : null}
            {thread.thread_timestamp ? <When iso={thread.thread_timestamp} /> : null}
            {thread.comment ? (
              <span className="normal-case text-text-secondary">
                <span className="hidden sm:inline">· </span>
                {thread.comment.length > 90 ? `${thread.comment.slice(0, 90)}…` : thread.comment}
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 font-mono text-[11px]">
          {/* Сколько файлов треда добавилось с начала отчётных суток (00:00 МСК):
              тот же период и тот же вид счётчика («+N»), что на карточке раздела.
              Идёт первым — прирост важнее общего числа. */}
          {thread.media_today ? (
            <span
              className="rounded-[3px] bg-accent-secondary/15 px-1.5 py-0.5 text-accent-secondary"
              title={`+${thread.media_today} за текущие сутки (с 00:00 МСК)`}
            >
              +{formatNumber(thread.media_today)}
            </span>
          ) : null}
          <span
            className="rounded-[3px] bg-ink-tertiary px-1.5 py-0.5 text-text-primary"
            title="Файлов треда в галерее"
          >
            {formatNumber(visibleCount)} в галерее
          </span>
        </div>
      </div>

      {/* Действия рядом с превью: продолжить с метки или открыть с начала */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-4 py-2 font-mono text-[11px]">
        <span className="uppercase tracking-wider text-text-muted">файлы треда</span>
        {resume ? (
          <span
            className="inline-flex items-center gap-1.5 text-accent-primary"
            title="На момент последнего просмотра этого треда"
          >
            <HistoryIcon className="h-3.5 w-3.5" />
            смотрели файл {resume.index + 1}
            {resume.total > 0 ? ` из ${resume.total}` : ""}
            <span className="text-text-muted">
              · {formatRelative(new Date(resume.at).toISOString())}
            </span>
          </span>
        ) : null}

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {resume && freshCount > 0 ? (
            <span
              className="rounded-[3px] bg-accent-secondary/15 px-1.5 py-0.5 text-accent-secondary"
              title="Новые файлы треда — в конце списка: продолжайте с метки, дальше дойдёте до них"
            >
              +{formatNumber(freshCount)} новых в конце
            </span>
          ) : null}
          {resume ? (
            <button
              type="button"
              onClick={onResume}
              disabled={opening}
              className="inline-flex items-center gap-1.5 rounded border border-accent-primary/50 px-2 py-1 text-accent-primary transition-colors hover:bg-accent-primary/15 disabled:opacity-50"
              title="Открыть тред на этом файле и листать дальше — с того места, где остановились"
            >
              {opening ? <SpinnerIcon className="h-3.5 w-3.5" /> : <PlayIcon className="h-3 w-3" />}
              продолжить
            </button>
          ) : null}
          <button
            type="button"
            onClick={onOpenAll}
            disabled={opening}
            className="inline-flex items-center gap-1.5 rounded border border-line px-2 py-1 text-text-secondary transition-colors hover:border-line-hover hover:text-text-primary disabled:opacity-50"
            title="Открыть тред с первого файла"
          >
            <ImageIcon className="h-3.5 w-3.5" />
            с начала
          </button>
          {resume ? (
            <button
              type="button"
              onClick={onForget}
              className="rounded p-1 text-text-muted transition-colors hover:text-text-primary"
              aria-label="Забыть точку возврата"
              title="Забыть: тред откроется с начала"
            >
              <CloseIcon className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </div>
      </div>

      {/* Превью файлов */}
      {preview.length > 0 ? (
        <div className="flex gap-2 overflow-x-auto px-4 py-3 sm:px-4">
          {preview.map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => onOpenAt(m.id)}
              aria-label={`Открыть: ${m.original_name}`}
              className={`group relative h-20 w-20 shrink-0 overflow-hidden rounded border bg-ink-tertiary transition-colors hover:border-accent-primary ${
                resume?.id === m.id ? "border-accent-primary/70" : "border-line"
              }`}
            >
              {m.thumb_url || m.url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={thumbSrc(m)}
                  alt={m.locked ? "" : m.original_name}
                  loading="lazy"
                  decoding="async"
                  referrerPolicy="no-referrer"
                  className={`h-full w-full object-cover ${m.locked ? "blur-[7px] scale-110" : ""}`}
                />
              ) : (
                <span className="flex h-full w-full items-center justify-center bg-ink-tertiary">
                  {m.media_type === "video" ? (
                    <FilmIcon className="h-5 w-5 text-text-muted" />
                  ) : (
                    <ImageIcon className="h-5 w-5 text-text-muted" />
                  )}
                </span>
              )}
              {m.locked ? (
                <span className="absolute inset-0 flex items-center justify-center bg-black/35">
                  <span className="inline-flex items-center gap-1 rounded-[3px] bg-black/70 px-1.5 py-0.5 font-mono text-[9px] uppercase text-accent-warning">
                    <LockIcon className="h-2.5 w-2.5" />
                    premium
                  </span>
                </span>
              ) : premiumState(m) === "granted" ? (
                <span
                  className="absolute left-0.5 top-0.5 inline-flex items-center gap-0.5 rounded-[3px] bg-black/60 px-1 py-0.5 text-[9px] uppercase text-accent-warning"
                  title="Премиум-контент: доступен по вашей подписке"
                >
                  <StarIcon className="h-2.5 w-2.5" />
                </span>
              ) : null}
              {/* Маркер видео: значок ▶ и длительность (как на карточках галереи) */}
              {m.media_type === "video" ? (
                <span
                  className="pointer-events-none absolute bottom-0.5 right-0.5 inline-flex items-center gap-0.5 rounded-[3px] bg-black/70 px-1 py-0.5 font-mono text-[9px] leading-none text-text-primary"
                  aria-hidden
                >
                  <PlayIcon className="h-2.5 w-2.5" />
                  {formatDuration(m.duration_seconds) || ""}
                </span>
              ) : null}
              {/* Метка «здесь вы остановились» — на том же превью, что и в точке возврата */}
              {resume?.id === m.id ? (
                <span
                  className="pointer-events-none absolute bottom-0.5 left-0.5 inline-flex items-center gap-0.5 rounded-[3px] bg-black/70 px-1 py-0.5 font-mono text-[9px] leading-none text-accent-primary"
                  title="Здесь вы остановились в прошлый раз"
                >
                  <HistoryIcon className="h-2.5 w-2.5" />
                </span>
              ) : null}
            </button>
          ))}
        </div>
      ) : (
        <div className="px-4 py-4 font-mono text-[11px] text-text-muted sm:px-4">
          {visibleCount === 0
            ? "в этом треде пока нет файлов"
            : "файлы пока недоступны (ещё не загружены)"}
        </div>
      )}
    </article>
  );
}
