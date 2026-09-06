"use client";

import { useEffect, useState } from "react";

import {
  EyeIcon,
  FilmIcon,
  ImageIcon,
  PlayIcon,
} from "@/components/icons";
import { formatBytes, formatCompact } from "@/lib/format";
import type { Board, MediaItem } from "@/lib/types";

interface MediaCardProps {
  media: MediaItem;
  board?: Board | null;
  /** Показывать бейдж [ТОП] (для ленты «Популярное»). */
  showTop?: boolean;
  onOpen: () => void;
}

function aspectOf(media: MediaItem): string {
  if (media.width && media.height) return `${media.width} / ${media.height}`;
  return media.media_type === "video" ? "16 / 9" : "1 / 1";
}

/**
 * Карточка медиа в стиле SLUICE: превью фото/видео (браузерный кадр) +
 * строка метаданных mono. При недоступности файла — аккуратный плейсхолдер.
 */
export default function MediaCard({ media, board, showTop = false, onOpen }: MediaCardProps) {
  const [failed, setFailed] = useState(false);
  const aspect = aspectOf(media);

  // Сброс состояния при смене файла (перелистывание/подгрузка)
  useEffect(() => {
    setFailed(false);
  }, [media.id, media.url]);

  const canShow = Boolean(media.url) && !failed;
  const isVideo = media.media_type === "video";

  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`Открыть: ${media.original_name}`}
      className="group block w-full cursor-pointer rounded text-left outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
    >
      {/* Превью */}
      <span
        className="relative block w-full overflow-hidden rounded border border-line bg-ink-secondary transition-colors duration-150 group-hover:border-accent-primary"
        style={{ aspectRatio: aspect }}
      >
        {canShow && !isVideo ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={media.url ?? undefined}
            alt={media.original_name}
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onError={() => setFailed(true)}
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : canShow && isVideo ? (
          <>
            {/* Браузерный кадр видео (preload=metadata) */}
            <video
              src={media.url ?? undefined}
              muted
              playsInline
              preload="metadata"
              aria-label={media.original_name}
              onError={() => setFailed(true)}
              className="absolute inset-0 h-full w-full object-cover"
            />
            <span className="absolute inset-0 flex items-center justify-center bg-black/35 transition-opacity group-hover:bg-black/25">
              <span className="flex h-11 w-11 items-center justify-center rounded bg-accent-primary text-ink-primary">
                <PlayIcon className="h-5 w-5 translate-x-0.5" />
              </span>
            </span>
          </>
        ) : (
          /* Плейсхолдер: нет URL или файл недоступен (лимиты B2 и т.п.) */
          <span className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-ink-secondary">
            {isVideo ? <FilmIcon className="h-6 w-6 text-text-muted" /> : <ImageIcon className="h-6 w-6 text-text-muted" />}
            <span className="badge badge-muted">недоступно</span>
          </span>
        )}

        {/* Бейджи поверх превью */}
        <span className="absolute left-1.5 top-1.5 flex items-center gap-1">
          {showTop ? <span className="badge badge-hot">топ</span> : null}
        </span>
        {isVideo && canShow ? (
          <span className="absolute bottom-1.5 right-1.5 flex items-center gap-1 rounded-[3px] bg-black/60 px-1.5 py-0.5 font-mono text-[10px] text-text-primary">
            <PlayIcon className="h-2.5 w-2.5" />
            видео
          </span>
        ) : null}
      </span>

      {/* Метаданные (mono) */}
      <span className="mt-1.5 block px-0.5">
        <span className="block truncate font-mono text-[11px] text-text-muted" title={media.original_name}>
          {board ? `/${board.slug}` : `#${media.board_id}`} · {media.original_name}
        </span>
        <span className="mt-0.5 flex items-center justify-between font-mono text-[11px] text-text-muted">
          <span>
            {formatBytes(media.file_size)}
            {media.width && media.height ? ` · ${media.width}×${media.height}` : ""}
          </span>
          <span className="inline-flex items-center gap-1">
            <EyeIcon className="h-3 w-3" />
            {formatCompact(media.views_count)}
          </span>
        </span>
      </span>
    </button>
  );
}

