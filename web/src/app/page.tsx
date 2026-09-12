import type { Metadata } from "next";
import { headers } from "next/headers";
import Link from "next/link";

import FilterChips from "@/components/FilterChips";
import Gallery from "@/components/Gallery";
import MediaShelf from "@/components/MediaShelf";
import { getBoards, getFeedPage, getStatus, getTopMedia } from "@/lib/data";
import { formatNumber } from "@/lib/format";
import type { MediaType } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * Главная — «витрина новинок»: фиксированное число файлов без автоподгрузки.
 * Полный поток живёт на `/new`, каталог разделов — на `/boards`.
 */
const HOME_SIZE = 24;
const POPULAR_SIZE = 6;

const TYPE_OPTIONS = [
  { value: "", label: "ВСЁ" },
  { value: "image", label: "КАРТИНКИ" },
  { value: "video", label: "ВИДЕО" },
];

function mediaType(value?: string | string[]): MediaType | null {
  const v = Array.isArray(value) ? value[0] : value;
  return v === "image" || v === "video" ? v : null;
}

export async function generateMetadata(): Promise<Metadata> {
  const status = await getStatus();
  const title = "Свежие файлы";
  const description = `Архив медиа с 2ch: ${formatNumber(status.files_total)} файлов в ${formatNumber(
    status.boards_visible,
  )} разделах. Свежие поступления, популярное и поиск по архиву.`;

  // og:image — превью самого свежего файла: ссылка в мессенджере получит картинку
  const feed = await getFeedPage(1, 1);
  const first = feed.items[0];
  let image: string | undefined;
  if (first?.thumb_url) {
    const host = headers().get("x-forwarded-host") ?? headers().get("host");
    const proto = headers().get("x-forwarded-proto") ?? "https";
    if (host) {
      image = first.thumb_url.startsWith("http")
        ? first.thumb_url
        : `${proto}://${host}${first.thumb_url}`;
    }
  }

  return {
    title,
    description,
    openGraph: { title, description, type: "website", images: image ? [image] : undefined },
  };
}


export default async function HomePage({
  searchParams,
}: {
  searchParams: { type?: string | string[]; free?: string | string[] };
}) {
  const type = mediaType(searchParams?.type);
  const rawFree = Array.isArray(searchParams?.free) ? searchParams.free[0] : searchParams?.free;
  const freeOnly = rawFree === "1";

  const [feed, status, popular, boards] = await Promise.all([
    getFeedPage(1, HOME_SIZE, type, freeOnly),
    getStatus(),
    getTopMedia("week", null, POPULAR_SIZE),
    getBoards(),
  ]);
  const boardsById = Object.fromEntries(boards.map((b) => [b.id, b]));

  return (
    <div className="py-6 sm:py-8">
      {/* Сводка архива: две строки, чтобы медиа попадало в первый экран */}
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h1 className="dredge-title">архив // новое</h1>
        <span className="font-mono text-[11px] text-text-muted">
          {formatNumber(status.files_total)} файлов · {formatNumber(status.threads_active)} тредов ·{" "}
          +{formatNumber(status.files_24h)} за сутки ·{" "}
          {status.parser_board ? `парсер: /${status.parser_board}` : "парсер: пауза"}
        </span>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <FilterChips typeOptions={TYPE_OPTIONS} />
        <span className="ml-auto font-mono text-[11px] text-text-muted">
          {formatNumber(feed.total)} по фильтру
        </span>
      </div>

      <Gallery
        key={`home-${type ?? "all"}-${freeOnly ? "free" : "all"}`}
        initial={feed}
        apiPath="/api/v1/feed"
        params={{ ...(type ? { type } : {}), ...(freeOnly ? { free: "1" } : {}) }}
        perPage={HOME_SIZE}
        boardsById={boardsById}
        infinite={false}
        moreHref="/new"
        moreLabel="Смотреть дальше в полном потоке →"
        emptyTitle="Пока нет файлов"
        emptyHint="Новые файлы появятся здесь после следующего прохода парсера."
      />

      {popular.length > 0 ? (
        <section className="mt-10">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="font-mono text-sm font-bold uppercase tracking-[0.08em] text-text-primary">
              популярное сейчас
            </h2>
            <Link
              href="/top"
              className="font-mono text-[11px] text-text-muted transition-colors hover:text-accent-primary"
            >
              весь топ →
            </Link>
          </div>
          <MediaShelf items={popular} boardsById={boardsById} showTop />
        </section>
      ) : null}

      {boards.length > 0 ? (
        <section className="mt-10">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="font-mono text-sm font-bold uppercase tracking-[0.08em] text-text-primary">
              разделы
            </h2>
            <Link
              href="/boards"
              className="font-mono text-[11px] text-text-muted transition-colors hover:text-accent-primary"
            >
              все разделы →
            </Link>
          </div>
          <div className="flex flex-wrap gap-2">
            {boards.map((b) => (
              <Link
                key={b.id}
                href={`/board/${b.slug}`}
                className="group inline-flex items-baseline gap-2 rounded border border-line bg-ink-secondary px-3 py-1.5 font-mono text-xs text-text-primary transition-colors hover:border-accent-primary"
                title={b.title || b.slug}
              >
                /{b.slug}
                <span className="text-[11px] text-text-muted transition-colors group-hover:text-accent-primary">
                  {formatNumber(b.media_count)}
                </span>
              </Link>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
