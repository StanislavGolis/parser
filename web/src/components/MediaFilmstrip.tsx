"use client";

import { useEffect, useRef, useState } from "react";

import { FilmIcon, ImageIcon } from "@/components/icons";
import { mediaUrl } from "@/lib/env";
import { thumbSrc } from "@/lib/media";
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
      aria-label={`Файл ${position}: ${media.original_name}`}
      aria-current={active ? "true" : undefined}
      title={media.original_name}
      className={`relative h-16 w-16 shrink-0 overflow-hidden rounded border transition-colors ${
        active ? "border-accent-primary ring-1 ring-accent-primary" : "border-line hover:border-line-hover"
      }`}
    >
      {near && media.thumb_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={thumbSrc(media)}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          className={`h-full w-full object-cover ${media.locked ? "blur-[5px] scale-110" : ""}`}
        />
      ) : near && media.url && isVideo && active ? (
        // Для текущего видео без постера показываем кадр (preload=metadata)
        <video
          src={mediaUrl(media.url)}
          muted
          playsInline
          preload="metadata"
          className="h-full w-full object-cover"
        />
      ) : (
        <span className="flex h-full w-full items-center justify-center bg-ink-tertiary text-text-muted">
          {isVideo ? <FilmIcon className="h-4 w-4" /> : <ImageIcon className="h-4 w-4" />}
        </span>
      )}
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
