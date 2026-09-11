"use client";

import { useCallback, useState } from "react";

import Lightbox from "@/components/Lightbox";
import { FilmIcon, ImageIcon, SpinnerIcon } from "@/components/icons";
import When from "@/components/When";
import { apiGet } from "@/lib/api";
import { mediaUrl } from "@/lib/env";
import { formatNumber, plural } from "@/lib/format";
import type { BoardThread, MediaItem, MediaList, ThreadList } from "@/lib/types";

const PER_PAGE = 15;
const MAX_PREVIEW = 8;

interface BoardThreadsProps {
  slug: string;
  initial: ThreadList;
}

/**
 * Доска в виде «список тредов → их файлы».
 * Кнопка открытия треда догружает все файлы треда и открывает Lightbox.
 */
export default function BoardThreads({ slug, initial }: BoardThreadsProps) {
  const [threads, setThreads] = useState<BoardThread[]>(initial.items);
  const [page, setPage] = useState(initial.page);
  const [total, setTotal] = useState(initial.total);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Lightbox с файлами конкретного треда
  const [lightbox, setLightbox] = useState<{ items: MediaItem[]; index: number } | null>(null);
  const [openingThread, setOpeningThread] = useState<number | null>(null);

  const hasMore = threads.length < total;

  const loadMore = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiGet<ThreadList>(
        `/api/v1/boards/${encodeURIComponent(slug)}/threads?page=${page + 1}&per_page=${PER_PAGE}`,
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
  }, [slug, page, loading]);

  async function openThread(threadId: number, startIndex = 0) {
    setOpeningThread(threadId);
    try {
      const q = new URLSearchParams({ thread: String(threadId), per_page: "300", sort: "new" });
      const data = await apiGet<MediaList>(`/api/v1/boards/${encodeURIComponent(slug)}/media?${q}`);
      if (data.items.length === 0) {
        setOpeningThread(null);
        return;
      }
      setLightbox({ items: data.items, index: Math.min(startIndex, data.items.length - 1) });
    } catch {
      setError("Не удалось открыть тред. Попробуйте ещё раз.");
    } finally {
      setOpeningThread(null);
    }
  }

  if (threads.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-neutral-800 py-20 text-center">
        <ImageIcon className="h-10 w-10 text-neutral-700" />
        <p className="font-medium text-neutral-300">В этом разделе пока пусто</p>
        <p className="text-sm text-neutral-500">
          Треды появятся после первого прохода парсера.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex flex-col gap-4">
        {threads.map((t) => (
          <ThreadCard
            key={t.thread_id}
            slug={slug}
            thread={t}
            opening={openingThread === t.thread_id}
            onOpenAll={() => void openThread(t.thread_id)}
            onOpenAt={(i) => void openThread(t.thread_id, i)}
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
          onClose={() => setLightbox(null)}
          onPrev={() =>
            setLightbox((lb) =>
              lb && lb.items.length > 1
                ? { ...lb, index: (lb.index - 1 + lb.items.length) % lb.items.length }
                : lb,
            )
          }
          onNext={() =>
            setLightbox((lb) =>
              lb && lb.items.length > 1 ? { ...lb, index: (lb.index + 1) % lb.items.length } : lb,
            )
          }
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
  onOpenAll,
  onOpenAt,
}: {
  slug: string;
  thread: BoardThread;
  opening: boolean;
  onOpenAll: () => void;
  onOpenAt: (index: number) => void;
}) {
  const title = thread.subject?.trim() || `Тред #${thread.thread_id}`;
  const preview = thread.preview;
  const visibleCount = thread.media_visible;
  const totalInCatalog = thread.files_count;

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
            {thread.thread_timestamp ? <When iso={thread.thread_timestamp} /> : null}
            <span>
              {formatNumber(thread.posts_count)} {plural(thread.posts_count, ["пост", "поста", "постов"])}
            </span>
            {thread.comment ? (
              <span className="normal-case text-text-secondary">
                <span className="hidden sm:inline">· </span>
                {thread.comment.length > 90 ? `${thread.comment.slice(0, 90)}…` : thread.comment}
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 font-mono text-[11px]">
          <span className="rounded-[3px] bg-ink-tertiary px-1.5 py-0.5 text-text-primary">
            {formatNumber(visibleCount)} в галерее
          </span>
          {totalInCatalog > 0 ? (
            <span className="rounded-[3px] bg-ink-tertiary px-1.5 py-0.5 text-text-muted">
              {formatNumber(totalInCatalog)} в каталоге
            </span>
          ) : null}
        </div>
      </div>

      {/* Превью файлов */}
      {preview.length > 0 ? (
        <div className="flex gap-2 overflow-x-auto px-4 py-3 sm:px-4">
          {preview.map((m, i) => (
            <button
              key={m.id}
              type="button"
              onClick={() => onOpenAt(i)}
              aria-label={`Открыть: ${m.original_name}`}
              className="group relative h-20 w-20 shrink-0 overflow-hidden rounded border border-line bg-ink-tertiary transition-colors hover:border-accent-primary"
            >
              {m.url && m.media_type === "image" ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={mediaUrl(m.url)}
                  alt={m.original_name}
                  loading="lazy"
                  decoding="async"
                  referrerPolicy="no-referrer"
                  className="h-full w-full object-cover"
                />
              ) : m.url ? (
                <span className="flex h-full w-full items-center justify-center bg-ink-tertiary">
                  <FilmIcon className="h-5 w-5 text-text-muted" />
                </span>
              ) : (
                <span className="flex h-full w-full items-center justify-center bg-ink-tertiary">
                  <ImageIcon className="h-5 w-5 text-text-muted" />
                </span>
              )}
            </button>
          ))}
          <button
            type="button"
            onClick={onOpenAll}
            disabled={opening}
            className="flex h-20 shrink-0 flex-col items-center justify-center gap-1 rounded border border-dashed border-line px-3 font-mono text-[11px] text-text-secondary transition-colors hover:border-line-hover hover:text-text-primary"
          >
            {opening ? <SpinnerIcon className="h-4 w-4" /> : "открыть все"}
          </button>
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
