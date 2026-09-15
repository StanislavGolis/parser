"use client";

import { useEffect, useState } from "react";

import Link from "next/link";

import MarkButton from "@/components/MarkButton";
import {
  EyeIcon,
  FilmIcon,
  ImageIcon,
  PlayIcon,
} from "@/components/icons";
import { formatBytes, formatCompact, formatDuration } from "@/lib/format";
import { isLocked, premiumState, blurSrc, thumbSrc, webSrc } from "@/lib/media";
import type { Board, MediaItem } from "@/lib/types";
import { useImgLoaded } from "@/lib/useImgLoaded";

interface MediaCardProps {
  media: MediaItem;
  board?: Board | null;
  /** Показывать бейдж [ТОП] (для ленты «Популярное»). */
  showTop?: boolean;
  /**
   * Загружать превью сразу, а не по появлению в вьюпорте: нужно первым
   * карточкам первого экрана (LCP — метрика ранжирования).
   */
  eager?: boolean;
  onOpen: () => void;
}

function aspectOf(media: MediaItem): string {
  if (media.width && media.height) return `${media.width} / ${media.height}`;
  return media.media_type === "video" ? "16 / 9" : "1 / 1";
}

/**
 * Карточка медиа в стиле DREDGER: превью фото/видео (браузерный кадр) +
 * строка метаданных mono. При недоступности файла — аккуратный плейсхолдер.
 */
export default function MediaCard({ media, board, showTop = false, eager = false, onOpen }: MediaCardProps) {
  const [failed, setFailed] = useState(false);
  // Готовность превью: пока не готово — видна размытая подложка (blur-up).
  // Хук проверяет `complete` (картинка может быть уже в кэше — тогда события
  // load не будет) и страхует таймаутом, поэтому «зависший» блюр невозможен.
  const img = useImgLoaded(`${media.id}:${media.thumb_url ?? media.url ?? ""}`);
  const aspect = aspectOf(media);
  const blur = blurSrc(media);
  // Постер видео: `thumb` → `thumb_blur`. Оригинал сюда не попадает (это видеофайл),
  // поэтому при отсутствии постера карточка покажет кадр плеером, а не «недоступно».
  const poster = thumbSrc(media);

  // Сброс состояния при смене файла (перелистывание/подгрузка)
  useEffect(() => {
    setFailed(false);
  }, [media.id, media.url]);

  const canShow = Boolean(media.url || media.thumb_url) && !failed;
  const isVideo = media.media_type === "video";
  const premium = premiumState(media);
  const locked = isLocked(media);

  return (
    <div
      // Клик по карточке открывает лайтбокс, ссылки внутри (раздел/тред) —
      // переходят на свои страницы: так у карточки есть и «открыть», и адрес.
      className="group relative cursor-pointer"
      role="button"
      tabIndex={0}
      aria-label={`Открыть: ${media.original_name}`}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
    >
      <span className="block w-full text-left outline-none">
        {/* Превью */}
        <span
          className={`relative block w-full overflow-hidden rounded border bg-ink-secondary transition-colors duration-150 ${
            premium === "locked"
              ? "border-accent-warning"
              : premium === "granted"
                ? "border-accent-secondary"
                : "border-line group-hover:border-accent-primary"
          }`}
          style={{ aspectRatio: aspect }}
        >
          {/* Подложка: размытый вариант, а если его нет — пульсирующий скелетон */}
          {canShow && !locked && !isVideo ? (
            blur ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={blur}
                alt=""
                aria-hidden
                loading={eager ? "eager" : "lazy"}
                decoding="async"
                referrerPolicy="no-referrer"
                className="absolute inset-0 h-full w-full scale-110 object-cover blur-lg"
              />
            ) : (
              <span className="absolute inset-0 animate-pulse bg-ink-tertiary" aria-hidden />
            )
          ) : null}

          {canShow && !isVideo ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              ref={img.setRef}
              src={thumbSrc(media)}
              alt={locked ? "" : media.original_name}
              loading={eager ? "eager" : "lazy"}
              fetchPriority={eager ? "high" : "auto"}
              decoding="async"
              referrerPolicy="no-referrer"
              onLoad={img.onLoad}
              onError={() => setFailed(true)}
              className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-300 ${
                img.loaded || locked ? "opacity-100" : "opacity-0"
              }`}
            />
          ) : canShow && isVideo ? (
            <>
              {/* Превью видео — постер-картинка: на мобильных браузер не
                  отрисовывает кадр из `<video preload="metadata">`, и карточка
                  выглядела пустой. Если постера нет (файл до бэкфилла вариантов),
                  показываем кадр плеером — «живой» превью лучше заглушки. */}
              {poster ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  ref={img.setRef}
                  src={poster}
                  alt={locked ? "" : media.original_name}
                  loading={eager ? "eager" : "lazy"}
                  fetchPriority={eager ? "high" : "auto"}
                  decoding="async"
                  referrerPolicy="no-referrer"
                  onLoad={img.onLoad}
                  onError={() => setFailed(true)}
                  className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-300 ${
                    img.loaded || locked ? "opacity-100" : "opacity-0"
                  }`}
                />
              ) : (
                <video
                  src={webSrc(media)}
                  muted
                  playsInline
                  preload="metadata"
                  aria-label={media.original_name}
                  controlsList="nodownload"
                  onContextMenu={(e) => e.preventDefault()}
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

          {/* Пометка премиума — одна и без иконки: состояние доступа читается по
              рамке (закрыт — accent-warning, доступен — accent-secondary), поэтому
              карточка не обрастает значками и не выглядит тяжелее обычной. */}
          <span className="absolute left-1.5 top-1.5 flex items-center gap-1">
            {premium ? (
              <span
                className={`badge ${
                  premium === "locked" ? "text-accent-warning" : "text-accent-secondary"
                }`}
                title={
                  premium === "locked"
                    ? "Премиум-контент: нужна подписка"
                    : "Премиум-контент: доступен по вашей подписке"
                }
              >
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
            {board ? (
              <>
                {/* Точное расположение: раздел / тред — и то и другое кликабельно */}
                <Link
                  href={`/board/${board.slug}`}
                  onClick={(e) => e.stopPropagation()}
                  className="transition-colors hover:text-accent-primary"
                  title={`Раздел /${board.slug}`}
                >
                  /{board.slug}
                </Link>
                <span className="text-text-muted">/</span>
                <Link
                  href={`/board/${board.slug}?thread=${media.thread_id}`}
                  onClick={(e) => e.stopPropagation()}
                  className="transition-colors hover:text-accent-primary"
                  title={`Открыть тред №${media.thread_id} в разделе /${board.slug}`}
                >
                  {media.thread_id}
                </Link>
              </>
            ) : (
              <span>
                #{media.board_id}/{media.thread_id}
              </span>
            )}
            <span className="hidden text-text-muted sm:inline"> · {media.original_name}</span>
          </span>
          {/* Размер и просмотры — только на широких экранах: на телефоне карточка
              остаётся максимально чистой (раздел / тред и превью) */}
          <span className="mt-0.5 hidden items-center justify-between font-mono text-[11px] text-text-muted sm:flex">
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
      </span>

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

