import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import DownloadButton from "@/components/DownloadButton";
import MarkButton from "@/components/MarkButton";
import TrackView from "@/components/TrackView";
import When from "@/components/When";
import { ArrowLeftIcon, DownloadIcon, EyeIcon, FilmIcon, LockIcon, StarIcon } from "@/components/icons";
import { ApiError } from "@/lib/api";
import { getBoards, getMediaDetail } from "@/lib/data";
import { absoluteUrl, mediaUrl } from "@/lib/env";
import { formatBytes, formatNumber } from "@/lib/format";
import { isLocked, premiumState } from "@/lib/media";
import type { MediaDetail } from "@/lib/types";

export const dynamic = "force-dynamic";

interface DetailProps {
  params: { id: string };
}

export async function generateMetadata({ params }: DetailProps): Promise<Metadata> {
  const numericId = Number(params.id);
  const notFoundMeta: Metadata = { title: "Файл не найден", robots: { index: false, follow: false } };
  if (!Number.isFinite(numericId)) return notFoundMeta;

  let media;
  try {
    media = await getMediaDetail(numericId);
  } catch {
    return notFoundMeta;
  }
  if (!media) return notFoundMeta;

  const kind = media.media_type === "video" ? "видео" : "изображение";
  const size = media.file_size ? `${formatBytes(media.file_size)}, ` : "";
  const dims = media.width && media.height ? `${media.width}×${media.height}` : "";
  const description = `${media.original_name} — ${kind} из архива: ${size}${dims}. Превью, просмотры и скачивание оригинала.`;

  return {
    title: media.original_name,
    description,
    alternates: { canonical: `/media/${numericId}` },
    openGraph: {
      title: media.original_name,
      description,
      type: media.media_type === "video" ? "video.other" : "website",
      // metadataBase в корневом layout превращает относительный путь в абсолютный
      images: media.thumb_url ? [media.thumb_url] : undefined,
    },
  };
}

export default async function MediaDetailPage({ params }: DetailProps) {
  const numericId = Number(params.id);

  if (!Number.isFinite(numericId)) notFound();

  let media: MediaDetail | null = null;
  try {
    media = await getMediaDetail(numericId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
  }
  if (!media) notFound();

  const boards = await getBoards();
  const board = boards.find((b) => b.id === media?.board_id);
  const premium = premiumState(media);
  const locked = isLocked(media);

  // Микроразметка для поисковых роботов: фото/видео с превью и датой.
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": media.media_type === "video" ? "VideoObject" : "ImageObject",
    name: media.original_name,
    contentUrl: absoluteUrl(media.url),
    thumbnailUrl: absoluteUrl(media.thumb_url),
    uploadDate: media.created_at,
    ...(media.width && media.height ? { width: media.width, height: media.height } : {}),
    ...(media.media_type === "video" && media.duration_seconds
      ? { duration: `PT${Math.round(media.duration_seconds)}S` }
      : {}),
  };

  return (
    <div className="container-site max-w-5xl py-6 sm:py-8">
      <script
        type="application/ld+json"
        // JSON-LD: сериализуем объект, экранируя «<», чтобы нельзя было вставить тег
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }}
      />
      <TrackView mediaId={media.id} />
      <Link
        href={board ? `/board/${board.slug}` : "/"}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-neutral-400 transition-colors hover:text-white"
      >
        <ArrowLeftIcon className="h-4 w-4" />
        {board ? `К разделу /${board.slug}` : "На главную"}
      </Link>

      <div className="overflow-hidden rounded-2xl border border-neutral-800 bg-neutral-900">
        {/* Медиа */}
        <div className="flex items-center justify-center bg-black/40 p-3 sm:p-6">
          {locked ? (
            <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
              <LockIcon className="h-8 w-8 text-amber-400" />
              <p className="font-mono text-xs uppercase tracking-widest text-amber-400">
                премиум-контент
              </p>
              <p className="max-w-sm text-xs text-neutral-400">
                Файл доступен по премиум-подписке. Активируйте премиум в профиле, чтобы смотреть и
                скачивать полные версии.
              </p>
              <Link href="/profile" className="btn-primary px-4 py-2 text-xs">
                Активировать премиум
              </Link>
            </div>
          ) : media.url ? (
            media.media_type === "image" ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={mediaUrl(media.url)}
                alt={media.original_name}
                referrerPolicy="no-referrer"
                className="max-h-[80vh] w-auto max-w-full rounded-lg object-contain"
              />
            ) : (
              <video src={mediaUrl(media.url)} controls preload="metadata" playsInline className="max-h-[80vh] w-auto max-w-full rounded-lg">
                Ваш браузер не поддерживает HTML5-видео.
              </video>
            )
          ) : (
            <p className="px-4 py-16 text-center text-sm text-neutral-500">
              Файл недоступен: объект не найден в хранилище.
            </p>
          )}
        </div>

        {/* Инфо */}
        <div className="border-t border-neutral-800 p-4 sm:p-6">
          <div className="flex flex-wrap items-center gap-2">
            {board ? (
              <Link
                href={`/board/${board.slug}`}
                className="rounded-md border border-neutral-700 bg-neutral-800 px-2 py-0.5 text-xs font-semibold text-amber-300 transition-colors hover:border-amber-500/60"
              >
                /{board.slug}
              </Link>
            ) : null}
            {premium === "granted" ? (
              <span className="chip bg-amber-500/15 text-amber-300">
                <StarIcon className="h-3.5 w-3.5" /> premium
              </span>
            ) : null}
            {media.media_type === "video" ? (
              <span className="chip bg-amber-500/15 text-amber-300">
                <FilmIcon className="h-3.5 w-3.5" /> видео
              </span>
            ) : (
              <span className="chip bg-sky-500/15 text-sky-300">фото</span>
            )}
            <span className="text-xs text-neutral-500">{media.mime_type}</span>
          </div>

          <h1 className="mt-3 break-words text-xl font-semibold">{media.original_name}</h1>

          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-neutral-400">
            <span className="inline-flex items-center gap-1.5">
              <EyeIcon className="h-4 w-4" /> {formatNumber(media.views_count)} просмотров
            </span>
            <span className="inline-flex items-center gap-1.5">
              <DownloadIcon className="h-4 w-4" /> {formatNumber(media.downloads_count)} скачиваний
            </span>
            <span>{formatBytes(media.file_size)}</span>
            {media.width && media.height ? (
              <span>
                {media.width}×{media.height}
              </span>
            ) : null}
            <When iso={media.created_at} />
            <span className="text-xs text-neutral-600">#{media.id}</span>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <DownloadButton mediaId={media.id} />
            <MarkButton
              mediaId={media.id}
              marksCount={media.marks_count ?? 0}
              marked={Boolean(media.marked)}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
