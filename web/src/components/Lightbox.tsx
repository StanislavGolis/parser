"use client";

import { useCallback, useEffect, useState } from "react";

import Link from "next/link";

import BoardBadge from "@/components/BoardBadge";
import DownloadButton from "@/components/DownloadButton";
import FavoriteButton from "@/components/FavoriteButton";
import MarkButton from "@/components/MarkButton";
import MediaFilmstrip from "@/components/MediaFilmstrip";
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  CloseIcon,
  DownloadIcon,
  EyeIcon,
  FilmIcon,
  ImageIcon,
  LockIcon,
  StarIcon,
} from "@/components/icons";
import { apiGet } from "@/lib/api";
import { mediaUrl } from "@/lib/env";
import { formatBytes, formatCompact, formatDuration } from "@/lib/format";
import { webSrc, premiumState } from "@/lib/media";
import type { BoardsById, MediaItem, ViewResult } from "@/lib/types";

interface LightboxProps {
  items: MediaItem[];
  index: number;
  boardsById?: BoardsById;
  onClose: () => void;
  onPrev: () => void;
  onNext: () => void;
  /** Перейти к произвольному файлу (клик по миниатюре карусели). */
  onSelect?: (index: number) => void;
}

export default function Lightbox({ items, index, boardsById, onClose, onPrev, onNext, onSelect }: LightboxProps) {
  const media = items[index];
  const board = media ? boardsById?.[media.board_id] : undefined;
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [media?.id, media?.url]);

  useEffect(() => {
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, []);

  useEffect(() => {
    if (!media) return;
    apiGet<ViewResult>(`/api/v1/media/${media.id}/view`).catch(() => {});
  }, [media]);

  const onKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft") onPrev();
      else if (e.key === "ArrowRight") onNext();
    },
    [onClose, onPrev, onNext],
  );

  useEffect(() => {
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onKeyDown]);

  if (!media) return null;

  const isVideo = media.media_type === "video";
  const premium = premiumState(media);
  const locked = premium === "locked";
  const canShow = !locked && Boolean(media.url || media.web_url || media.thumb_url) && !failed;
  const position = `${index + 1} / ${items.length}`;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-[#050708]"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={media.original_name}
    >
      <div className="flex items-start justify-between gap-4 border-b border-line px-4 py-2.5 sm:px-6">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-text-secondary">
            {board ? <BoardBadge board={board} /> : null}
            <span className="truncate">{media.original_name}</span>
            <span className="text-text-muted">{formatBytes(media.file_size)}</span>
            {media.width && media.height ? (
              <span className="text-text-muted">
                {media.width}×{media.height}
              </span>
            ) : null}
            {isVideo ? (
              <span className="badge badge-hot">
                <FilmIcon className="h-2.5 w-2.5" />
                {`видео${formatDuration(media.duration_seconds) ? ` ${formatDuration(media.duration_seconds)}` : ""}`}
              </span>
            ) : null}
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
            ) : null}
          </div>
          {media.source_md5 || media.file_hash ? (
            <div className="mt-1 break-all font-mono text-[10px] leading-relaxed text-text-muted">
              {media.source_md5 ? <>MD5: {media.source_md5}</> : null}
              {media.source_md5 && media.file_hash ? <> &nbsp;·&nbsp; </> : null}
              {media.file_hash ? <>SHA-256: {media.file_hash}</> : null}
            </div>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded p-2 text-text-secondary transition-colors hover:bg-ink-tertiary hover:text-text-primary"
          aria-label="Закрыть (Esc)"
        >
          <CloseIcon className="h-5 w-5" />
        </button>
      </div>

      {/* Медиа */}
      <div className="flex min-h-0 flex-1 items-center justify-center p-3 sm:p-6">
        {canShow ? (
          isVideo ? (
            <video
              src={webSrc(media)}
              controls
              autoPlay
              playsInline
              onError={() => setFailed(true)}
              className="max-h-full w-auto max-w-full rounded"
            >
              Ваш браузер не поддерживает HTML5-видео.
            </video>
          ) : (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={webSrc(media)}
              alt={media.original_name}
              referrerPolicy="no-referrer"
              onError={() => setFailed(true)}
              className="max-h-full w-auto max-w-full rounded object-contain"
            />
          )
        ) : locked ? (
          <div className="flex flex-col items-center gap-3 rounded border border-accent-warning/40 bg-ink-secondary px-8 py-12 text-center">
            <LockIcon className="h-8 w-8 text-accent-warning" />
            <p className="font-mono text-[11px] uppercase tracking-widest text-accent-warning">
              премиум-контент
            </p>
            <p className="max-w-sm text-xs text-text-secondary">
              Файл доступен по премиум-подписке. Активируйте премиум в профиле, чтобы смотреть и
              скачивать полные версии.
            </p>
            <Link href="/profile" className="btn-primary px-4 py-2 text-xs">
              Активировать премиум
            </Link>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3 rounded border border-line bg-ink-secondary px-8 py-12 text-center">
            {isVideo ? <FilmIcon className="h-8 w-8 text-text-muted" /> : <ImageIcon className="h-8 w-8 text-text-muted" />}
            <p className="font-mono text-[11px] uppercase tracking-widest text-text-muted">
              файл недоступен
            </p>
            <p className="max-w-sm text-xs text-text-secondary">
              Не удалось загрузить объект из хранилища (возможно, временный лимит или файл удалён).
            </p>
          </div>
        )}
      </div>

      {/* Карусель файлов треда (быстрая навигация) */}
      {onSelect ? <MediaFilmstrip items={items} index={index} onSelect={onSelect} /> : null}

      {/* Нижняя панель */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-2.5 sm:px-6">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-text-secondary">
          <span className="inline-flex items-center gap-1.5">
            <EyeIcon className="h-3.5 w-3.5" />
            {formatCompact(media.views_count)} просмотров
          </span>
          <span className="inline-flex items-center gap-1.5">
            <DownloadIcon className="h-3.5 w-3.5" />
            {formatCompact(media.downloads_count)} скачиваний
          </span>
          {/* Метка («отличный контент») и избранное — требуют аккаунт */}
          <MarkButton
            key={`mark-${media.id}`}
            mediaId={media.id}
            marksCount={media.marks_count ?? 0}
            marked={Boolean(media.marked)}
          />
          <FavoriteButton
            key={`fav-${media.id}`}
            mediaId={media.id}
            favorited={Boolean(media.favorited)}
          />
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onPrev}
            disabled={items.length < 2}
            className="btn-small px-2.5 py-1.5"
            aria-label="Предыдущий (←)"
          >
            <ChevronLeftIcon className="h-4 w-4" />
          </button>
          <span className="min-w-14 text-center font-mono text-[11px] tabular-nums text-text-muted">
            {position}
          </span>
          <button
            type="button"
            onClick={onNext}
            disabled={items.length < 2}
            className="btn-small px-2.5 py-1.5"
            aria-label="Следующий (→)"
          >
            <ChevronRightIcon className="h-4 w-4" />
          </button>
          {locked ? (
            <Link href="/profile" className="btn-primary px-3 py-1.5 text-xs">
              <LockIcon className="h-4 w-4" />
              Premium
            </Link>
          ) : (
            <DownloadButton mediaId={media.id} size="sm" />
          )}
        </div>
      </div>
    </div>
  );
}
