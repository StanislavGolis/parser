"use client";

import { useEffect, useState } from "react";

import MarkButton from "@/components/MarkButton";
import {
  EyeIcon,
  FilmIcon,
  ImageIcon,
  LockIcon,
  PlayIcon,
  StarIcon,
} from "@/components/icons";
import { mediaUrl } from "@/lib/env";
import { formatBytes, formatCompact, formatDuration } from "@/lib/format";
import { isLocked, premiumState, thumbSrc } from "@/lib/media";
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
 * Карточка медиа в стиле DREDGE: превью фото/видео (браузерный кадр) +
 * строка метаданных mono. При недоступности файла — аккуратный плейсхолдер.
 */
export default function MediaCard({ media, board, showTop = false, onOpen }: MediaCardProps) {
  const [failed, setFailed] = useState(false);
  const aspect = aspectOf(media);

  // Сброс состояния при смене файла (перелистывание/подгрузка)
  useEffect(() => {
    setFailed(false);
  }, [media.id, media.url]);

  const canShow = Boolean(media.url || media.thumb_url) && !failed;
  const isVideo = media.media_type === "video";
  const premium = premiumState(media);
  const locked = isLocked(media);

  return (
    <div className="group relative">
      <button
        type="button"
        onClick={onOpen}
        aria-label={`Открыть: ${media.original_name}`}
        className="block w-full cursor-pointer rounded text-left outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
      >
        {/* Превью */}
        <span
          className="relative block w-full overflow-hidden rounded border border-line bg-ink-secondary transition-colors duration-150 group-hover:border-accent-primary"
          style={{ aspectRatio: aspect }}
        >
          {canShow && !isVideo ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={thumbSrc(media)}
              alt={locked ? "" : media.original_name}
              loading="lazy"
              decoding="async"
              referrerPolicy="no-referrer"
              onError={() => setFailed(true)}
              className={`absolute inset-0 h-full w-full object-cover ${locked ? "blur-[8px] scale-110" : ""}`}
            />
          ) : canShow && isVideo ? (
            <>
              {/* Постер-дериватив, иначе браузерный кадр (preload=metadata) */}
              {media.thumb_url || locked ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={thumbSrc(media)}
                  alt={locked ? "" : media.original_name}
                  loading="lazy"
                  decoding="async"
                  referrerPolicy="no-referrer"
                  onError={() => setFailed(true)}
                  className={`absolute inset-0 h-full w-full object-cover ${locked ? "blur-[8px] scale-110" : ""}`}
                />
              ) : (
                <video
                  src={mediaUrl(media.url)}
                  muted
                  playsInline
                  preload="metadata"
                  aria-label={media.original_name}
                  onError={() => setFailed(true)}
                  className="absolute inset-0 h-full w-full object-cover"
                />
              )}
              {locked ? null : (
                <span className="absolute inset-0 flex items-center justify-center bg-black/35 transition-opacity group-hover:bg-black/25">
                  <span className="flex h-11 w-11 items-center justify-center rounded bg-accent-primary text-ink-primary">
                    <PlayIcon className="h-5 w-5 translate-x-0.5" />
                  </span>
                </span>
              )}
            </>
          ) : (
            /* Плейсхолдер: нет URL или файл недоступен (лимиты S3 и т.п.) */
            <span className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-ink-secondary">
              {isVideo ? <FilmIcon className="h-6 w-6 text-text-muted" /> : <ImageIcon className="h-6 w-6 text-text-muted" />}
              <span className="badge badge-muted">недоступно</span>
            </span>
          )}

          {/* Бейджи поверх превью: замок — нет доступа, звезда — премиум по подписке */}
          <span className="absolute left-1.5 top-1.5 flex items-center gap-1">
            {premium === "locked" ? (
              <span className="badge badge-warn" title="Премиум-контент: нужна подписка">
                <LockIcon className="h-2.5 w-2.5" />
                premium
              </span>
            ) : premium === "granted" ? (
              <span
                className="badge badge-warn"
                title="Премиум-контент: доступен по вашей подписке"
              >
                <StarIcon className="h-2.5 w-2.5" />
                premium
              </span>
            ) : showTop ? (
              <span className="badge badge-hot">топ</span>
            ) : null}
          </span>
          {isVideo && canShow && !locked ? (
            <span className="absolute bottom-1.5 right-1.5 flex items-center gap-1 rounded-[3px] bg-black/60 px-1.5 py-0.5 font-mono text-[10px] text-text-primary">
              <PlayIcon className="h-2.5 w-2.5" />
              {formatDuration(media.duration_seconds) || "видео"}
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

      {/* Метка — поверх превью; клик не открывает lightbox */}
      <span className="absolute right-1.5 top-1.5 z-10 flex items-center gap-1">
        <MarkButton
          mediaId={media.id}
          marksCount={media.marks_count ?? 0}
          marked={Boolean(media.marked)}
          variant="overlay"
        />
      </span>
    </div>
  );
}

