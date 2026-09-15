"use client";

import { useEffect, useRef, useState } from "react";

import { FilmIcon, ImageIcon, PlayIcon } from "@/components/icons";
import { formatDuration } from "@/lib/format";
import { thumbSrc, webSrc } from "@/lib/media";
import type { MediaItem } from "@/lib/types";

/**
 * Миниатюра ленты. Превью монтируется только когда элемент попадает в зону
 * видимости (IntersectionObserver) — иначе при треде в 300 файлов браузер
 * тянул бы все картинки сразу.
 */
function Thumb({
  media,
  active,
  position,
  onSelect,
}: {
  media: MediaItem;
  active: boolean;
  position: number;
  onSelect: () => void;
}) {
  const ref = useRef<HTMLButtonElement | null>(null);
  const [near, setNear] = useState(false);
  const isVideo = media.media_type === "video";
  // Постер миниатюры (thumb → размытый вариант) и кадр-фолбэк для видео без постера
  const preview = thumbSrc(media);
  const video = isVideo ? webSrc(media) : undefined;

  useEffect(() => {
    const el = ref.current;
    if (!el || near) return;
    if (typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setNear(true);
          io.disconnect();
        }
      },
      { root: null, rootMargin: "400px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [near]);

  // Активную миниатюру держим в центре ленты
  useEffect(() => {
    if (active) {
      ref.current?.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
    }
  }, [active]);

  return (
    <button
      ref={ref}
      type="button"
      onClick={onSelect}
      aria-label={`${isVideo ? "Видео" : "Файл"} ${position}: ${media.original_name}`}
      aria-current={active ? "true" : undefined}
      title={
        isVideo
          ? `Видео${formatDuration(media.duration_seconds) ? ` ${formatDuration(media.duration_seconds)}` : ""}: ${media.original_name}`
          : media.original_name
      }
      className={`relative h-16 w-16 shrink-0 overflow-hidden rounded border transition-colors ${
        active ? "border-accent-primary ring-1 ring-accent-primary" : "border-line hover:border-line-hover"
      }`}
    >
      {near && preview ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={preview}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          className={`h-full w-full object-cover ${media.locked ? "blur-[5px] scale-110" : ""}`}
        />
      ) : near && isVideo && active && video ? (
        // Постера нет (файл до бэкфилла вариантов) — для текущего видео показываем
        // кадр плеером: на мобильных он может не отрисоваться, но это лучше пустой
        // миниатюры, а после бэкфилла здесь будет обычный постер.
        <video
          src={video}
          muted
          playsInline
          preload="metadata"
          controlsList="nodownload"
          onContextMenu={(e) => e.preventDefault()}
          className="h-full w-full object-cover"
        />
      ) : (
        <span className="flex h-full w-full items-center justify-center bg-ink-tertiary text-text-muted">
          {isVideo ? <FilmIcon className="h-4 w-4" /> : <ImageIcon className="h-4 w-4" />}
        </span>
      )}

      {/* Маркер видео: значок ▶ и длительность (как на карточках галереи) */}
      {isVideo ? (
        <span
          className="pointer-events-none absolute bottom-0.5 right-0.5 inline-flex items-center gap-0.5 rounded-[3px] bg-black/70 px-1 py-0.5 font-mono text-[9px] leading-none text-text-primary"
          aria-hidden
        >
          <PlayIcon className="h-2.5 w-2.5" />
          {formatDuration(media.duration_seconds) || ""}
        </span>
      ) : null}
    </button>
  );
}

/** Горизонтальная карусель файлов треда для быстрой навигации в Lightbox. */
export default function MediaFilmstrip({
  items,
  index,
  onSelect,
}: {
  items: MediaItem[];
  index: number;
  onSelect: (index: number) => void;
}) {
  if (items.length < 2) return null;
  return (
    <div
      className="border-t border-line bg-ink-primary/60 px-2 py-2 sm:px-4"
      data-wheel-ignore
    >
      <div className="flex gap-1.5 overflow-x-auto pb-1">
        {items.map((m, i) => (
          <Thumb
            key={m.id}
            media={m}
            active={i === index}
            position={i + 1}
            onSelect={() => onSelect(i)}
          />
        ))}
      </div>
    </div>
  );
}
