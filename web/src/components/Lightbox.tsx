"use client";

import { useCallback, useEffect } from "react";

import BoardBadge from "@/components/BoardBadge";
import DownloadButton from "@/components/DownloadButton";
import When from "@/components/When";
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  CloseIcon,
  DownloadIcon,
  EyeIcon,
  FilmIcon,
} from "@/components/icons";
import { apiGet } from "@/lib/api";
import { formatBytes, formatNumber } from "@/lib/format";
import type { BoardsById, MediaItem, ViewResult } from "@/lib/types";

interface LightboxProps {
  items: MediaItem[];
  index: number;
  boardsById?: BoardsById;
  onClose: () => void;
  onPrev: () => void;
  onNext: () => void;
}

/**
 * Просмотр файла на весь экран (lightbox): HTML5-плеер для видео,
 * навигация ←/→, счётчик просмотра и кнопка скачивания.
 */
export default function Lightbox({ items, index, boardsById, onClose, onPrev, onNext }: LightboxProps) {
  const media = items[index];
  const board = media ? boardsById?.[media.board_id] : undefined;

  // Блокируем скролл подложки на время показа.
  useEffect(() => {
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, []);

  // Считаем просмотр файла на бэкенде (дедуп по IP там же).
  useEffect(() => {
    if (!media) return;
    apiGet<ViewResult>(`/api/v1/media/${media.id}/view`).catch(() => {
      /* Просмотр не критичен — молча пропускаем ошибки сети/rate-limit. */
    });
  }, [media]);

  // Клавиатура: Esc / ← / →
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

  const position = `${index + 1} / ${items.length}`;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-neutral-950/95 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={media.original_name}
    >
      {/* Верхняя панель */}
      <div className="flex items-start justify-between gap-4 border-b border-neutral-800 px-4 py-3 sm:px-6">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {board ? <BoardBadge board={board} /> : null}
            {media.media_type === "video" ? (
              <span className="chip bg-amber-500/15 text-amber-300">
                <FilmIcon className="h-3.5 w-3.5" /> видео
              </span>
            ) : (
              <span className="chip bg-sky-500/15 text-sky-300">фото</span>
            )}
            <span className="text-xs text-neutral-500">{media.mime_type}</span>
          </div>
          <h2 className="mt-1.5 truncate text-sm font-medium text-neutral-100" title={media.original_name}>
            {media.original_name}
          </h2>
        </div>

        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded-lg p-2 text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-white"
          aria-label="Закрыть (Esc)"
        >
          <CloseIcon className="h-5 w-5" />
        </button>
      </div>

      {/* Медиа */}
      <div className="flex min-h-0 flex-1 items-center justify-center p-3 sm:p-6">
        {media.url ? (
          media.media_type === "image" ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={media.url}
              alt={media.original_name}
              referrerPolicy="no-referrer"
              className="max-h-[74vh] w-auto max-w-full rounded-lg object-contain shadow-2xl"
            />
          ) : (
            <video
              src={media.url}
              controls
              autoPlay
              playsInline
              className="max-h-[74vh] w-auto max-w-full rounded-lg"
            >
              Ваш браузер не поддерживает HTML5-видео.
            </video>
          )
        ) : (
          <div className="rounded-xl border border-dashed border-neutral-700 px-6 py-10 text-center text-sm text-neutral-400">
            Файл недоступен (нет объекта в хранилище).
          </div>
        )}
      </div>

      {/* Нижняя панель */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-neutral-800 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-4 text-xs text-neutral-400">
          <span className="inline-flex items-center gap-1.5">
            <EyeIcon className="h-4 w-4" />
            {formatNumber(media.views_count)}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <DownloadIcon className="h-4 w-4" />
            {formatNumber(media.downloads_count)}
          </span>
          <span className="hidden sm:inline">
            {formatBytes(media.file_size)}
            {media.width && media.height ? ` · ${media.width}×${media.height}` : ""}
          </span>
          <When iso={media.created_at} className="hidden sm:inline" />
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onPrev}
            disabled={items.length < 2}
            className="btn-ghost px-2.5 py-1.5"
            aria-label="Предыдущий (←)"
          >
            <ChevronLeftIcon className="h-4 w-4" />
          </button>
          <span className="min-w-16 text-center text-xs tabular-nums text-neutral-500">{position}</span>
          <button
            type="button"
            onClick={onNext}
            disabled={items.length < 2}
            className="btn-ghost px-2.5 py-1.5"
            aria-label="Следующий (→)"
          >
            <ChevronRightIcon className="h-4 w-4" />
          </button>
          <DownloadButton mediaId={media.id} size="sm" />
        </div>
      </div>
    </div>
  );
}

