import { EyeIcon, FilmIcon, ImageIcon, PlayIcon } from "@/components/icons";
import When from "@/components/When";
import { formatBytes, formatNumber } from "@/lib/format";
import type { Board, MediaItem } from "@/lib/types";

interface MediaCardProps {
  media: MediaItem;
  board?: Board | null;
  onOpen: () => void;
}

/**
 * Плитка в masonry-сетке: превью изображения или первый кадр видео,
 * метки (тип, доска, просмотры) и имя файла.
 */
export default function MediaCard({ media, board, onOpen }: MediaCardProps) {
  const hasDims = Boolean(media.width && media.height);
  const aspect =
    hasDims && media.width && media.height
      ? `${media.width}/${media.height}`
      : media.media_type === "video"
        ? "16 / 9"
        : undefined;

  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`Открыть: ${media.original_name}`}
      className="group block w-full cursor-pointer rounded-xl text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
    >
      <span className="relative block w-full overflow-hidden rounded-xl border border-neutral-800 bg-neutral-900 transition-colors group-hover:border-neutral-600">
        {media.url ? (
          media.media_type === "image" ? (
            <img
              src={media.url}
              alt={media.original_name}
              loading="lazy"
              decoding="async"
              referrerPolicy="no-referrer"
              className="block w-full h-auto object-cover transition-transform duration-300 group-hover:scale-[1.02]"
            />
          ) : (
            <span
              className="relative block w-full overflow-hidden bg-neutral-900"
              style={{ aspectRatio: aspect }}
            >
              <video
                src={media.url}
                muted
                playsInline
                preload="metadata"
                aria-label={media.original_name}
                className="absolute inset-0 h-full w-full object-contain"
              />
              <span className="absolute inset-0 flex items-center justify-center bg-black/30 opacity-90 transition-opacity group-hover:opacity-100">
                <span className="flex h-12 w-12 items-center justify-center rounded-full bg-amber-500/90 text-neutral-950 shadow-lg">
                  <PlayIcon className="h-6 w-6 translate-x-0.5" />
                </span>
              </span>
            </span>
          )
        ) : (
          <span
            className="relative flex w-full items-center justify-center bg-neutral-900"
            style={{ aspectRatio: aspect ?? "1 / 1" }}
          >
            <ImageIcon className="h-8 w-8 text-neutral-700" />
          </span>
        )}

        {/* Верхние метки */}
        <span className="absolute left-2 top-2 flex items-center gap-1.5">
          {board ? (
            <span className="rounded-md bg-black/55 px-1.5 py-0.5 text-[11px] font-semibold text-amber-300 backdrop-blur-sm">
              /{board.slug}
            </span>
          ) : null}
        </span>
        <span className="absolute right-2 top-2 flex items-center gap-1.5">
          {media.media_type === "video" ? (
            <span className="chip bg-black/60 text-neutral-200 backdrop-blur-sm">
              <FilmIcon className="h-3 w-3" />
              видео
            </span>
          ) : null}
          <span className="chip bg-black/60 text-neutral-200 backdrop-blur-sm">
            <EyeIcon className="h-3 w-3" />
            {formatNumber(media.views_count)}
          </span>
        </span>
      </span>

      <span className="mt-1.5 block px-0.5">
        <span className="block truncate text-[13px] text-neutral-300" title={media.original_name}>
          {media.original_name}
        </span>
        <span className="mt-0.5 flex items-center justify-between gap-2 text-[11px] text-neutral-500">
          <When iso={media.created_at} />
          <span>{formatBytes(media.file_size)}</span>
        </span>
      </span>
    </button>
  );
}
