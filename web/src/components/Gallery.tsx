"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import EmptyState from "@/components/EmptyState";
import Lightbox from "@/components/Lightbox";
import MediaCard from "@/components/MediaCard";
import { SpinnerIcon } from "@/components/icons";
import { ApiError, apiGet } from "@/lib/api";
import type { BoardsById, MediaItem, MediaList } from "@/lib/types";

interface GalleryProps {
  /** Первая страница, полученная на сервере (SSR). */
  initial: MediaList;
  /** Путь API без query, например /api/v1/feed. */
  apiPath: string;
  /** Стабильные query-параметры списка (кроме page/per_page). */
  params?: Record<string, string>;
  perPage: number;
  boardsById?: BoardsById;
  /** Показывать бейдж [ТОП] на карточках. */
  showTop?: boolean;
  /**
   * Автодогрузка страниц при скролле. `false` — «витрина»: показываем ровно
   * полученную с сервера страницу и ссылку на полный список (главная страница).
   */
  infinite?: boolean;
  /** Куда ведёт ссылка «показать больше» в режиме витрины. */
  moreHref?: string;
  moreLabel?: string;
  emptyTitle?: string;
  emptyHint?: string;
}

/**
 * Masonry-галерея с клиентской догрузкой страниц (infinite scroll).
 * Требует "use client", т.к. догрузка идёт fetch из браузера.
 */
export default function Gallery({
  initial,
  apiPath,
  params = {},
  perPage,
  boardsById,
  showTop = false,
  infinite = true,
  moreHref,
  moreLabel,
  emptyTitle,
  emptyHint,
}: GalleryProps) {
  const [items, setItems] = useState<MediaItem[]>(initial.items);
  const [total, setTotal] = useState(initial.total);
  const [page, setPage] = useState(initial.page);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoPaused, setAutoPaused] = useState(false);
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);

  const hasMore = items.length < total;
  const queryKey = useMemo(() => Object.entries(params).map(([k, v]) => `${k}=${v}`).join("&"), [params]);

  const loadMore = useCallback(async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    setLoading(true);
    setError(null);

    const q = new URLSearchParams({ page: String(page + 1), per_page: String(perPage) });
    Object.entries(params).forEach(([k, v]) => {
      if (v) q.set(k, v);
    });

    try {
      const data = await apiGet<MediaList>(`${apiPath}?${q.toString()}`);
      setItems((prev) => {
        const seen = new Set(prev.map((m) => m.id));
        const fresh = data.items.filter((m) => !seen.has(m.id));
        return fresh.length > 0 ? [...prev, ...fresh] : prev;
      });
      setPage(data.page);
      setTotal(data.total);
      setAutoPaused(false);
    } catch (err) {
      setError(err instanceof ApiError && err.status ? `Не удалось загрузить (HTTP ${err.status})` : "Нет соединения с сервером");
      setAutoPaused(true);
    } finally {
      busyRef.current = false;
      setLoading(false);
    }
  }, [apiPath, page, perPage, params]);

  const retry = useCallback(() => {
    setAutoPaused(false);
    setError(null);
    void loadMore();
  }, [loadMore]);

  // Infinite scroll: догружаем, когда sentinel появляется в зоне видимости.
  // В режиме витрины (infinite=false) автодогрузки нет — пользователь уходит
  // в полный список по ссылке.
  useEffect(() => {
    if (!infinite) return;
    const node = sentinelRef.current;
    if (!node || !hasMore || loading || autoPaused || error) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) void loadMore();
      },
      { rootMargin: "900px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [loadMore, hasMore, loading, autoPaused, error, queryKey, items.length]);

  const step = useCallback(
    (dir: 1 | -1) => {
      setOpenIndex((cur) => {
        if (cur === null || items.length < 2) return cur;
        return (cur + dir + items.length) % items.length;
      });
    },
    [items.length],
  );

  const showEmpty = items.length === 0 && !loading && !error;

  return (
    <div>
      {showEmpty ? (
        <EmptyState title={emptyTitle} hint={emptyHint} />
      ) : (
        <>
          <div className="masonry">
            {items.map((media, idx) => (
              <div key={media.id} className="masonry-item">
                <MediaCard
                  media={media}
                  board={boardsById ? boardsById[media.board_id] : undefined}
                  showTop={showTop}
                  onOpen={() => setOpenIndex(idx)}
                />
              </div>
            ))}
          </div>

          {items.length > 0 && items.length < total ? (
            <div className="mt-4 text-center font-mono text-[11px] text-text-muted">
              показано {items.length} из {total}
            </div>
          ) : null}
        </>
      )}

      {error ? (
        <div className="mt-6 flex flex-col items-center gap-3">
          <p className="text-sm text-text-secondary">{error}</p>
          <button type="button" onClick={retry} className="btn-small">
            Повторить загрузку
          </button>
        </div>
      ) : null}

      {/* Sentinel для infinite scroll (только в режиме полного списка) */}
      {infinite && hasMore && !error ? (
        <div ref={sentinelRef} className="flex min-h-16 items-center justify-center py-6">
          {loading ? (
            <span className="inline-flex items-center gap-2 font-mono text-[11px] text-text-secondary">
              <SpinnerIcon className="h-4 w-4 animate-spin" />
              загрузка ещё…
            </span>
          ) : (
            <span className="font-mono text-[11px] text-text-muted">••• прокрутите ниже</span>
          )}
        </div>
      ) : null}

      {/* Режим витрины: без автодогрузки, но с явной ссылкой в полный список */}
      {!infinite && moreHref && items.length > 0 ? (
        <div className="mt-6 text-center">
          <Link href={moreHref} className="btn-ghost">
            {moreLabel ?? "Показать больше"}
          </Link>
        </div>
      ) : null}

      {openIndex !== null ? (
        <Lightbox
          items={items}
          index={openIndex}
          boardsById={boardsById}
          onClose={() => setOpenIndex(null)}
          onPrev={() => step(-1)}
          onNext={() => step(1)}
          onSelect={(i) => setOpenIndex(i)}
        />
      ) : null}
    </div>
  );
}
