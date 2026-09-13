import type { Metadata } from "next";
import { cookies, headers } from "next/headers";
import Link from "next/link";

import FilterChips from "@/components/FilterChips";
import Gallery from "@/components/Gallery";
import MediaShelf from "@/components/MediaShelf";
import TrackedLink from "@/components/TrackedLink";
import VisitStamp from "@/components/VisitStamp";
import { getBoards, getFeedPage, getStatus, getTopMedia } from "@/lib/data";
import { SITE_URL } from "@/lib/env";
import { formatNumber, plural } from "@/lib/format";
import type { MediaType } from "@/lib/types";
import { LAST_VISIT_COOKIE, parseVisitDate, visitLabel } from "@/lib/visit";

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
    // Абсолютный заголовок: главная — основная точка входа из поиска.
    title: { absolute: "DREDGER — медиа-архив: свежие фото и видео" },
    description,
    alternates: { canonical: "/" },
    // Возрастная метка: архив целиком 18+, честная маркировка для поисковиков
    other: { rating: "adult" },
    openGraph: {
      title: "DREDGER — медиа-архив",
      description,
      type: "website",
      images: image ? [image] : undefined,
    },
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

  // «Новое с прошлого визита»: cookie пишет VisitStamp (клиент), читаем здесь.
  const lastVisit = parseVisitDate(cookies().get(LAST_VISIT_COOKIE)?.value);

  const [feed, status, popular, boards, fresh] = await Promise.all([
    getFeedPage(1, HOME_SIZE, type, freeOnly),
    getStatus(),
    getTopMedia("week", null, POPULAR_SIZE),
    getBoards(),
    lastVisit
      ? getFeedPage(1, 1, null, false, lastVisit.toISOString())
      : Promise.resolve(null),
  ]);
  const boardsById = Object.fromEntries(boards.map((b) => [b.id, b]));
  const freshCount = fresh?.total ?? 0;

  // Микроразметка сайта: имя + поиск (потенциальный «sitelinks searchbox»).
  const siteJsonLd = {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: "DREDGER",
    alternateName: "DREDGER — медиа-архив",
    url: SITE_URL,
    inLanguage: "ru-RU",
    potentialAction: {
      "@type": "SearchAction",
      target: { "@type": "EntryPoint", urlTemplate: `${SITE_URL}/search?q={search_term_string}` },
      "query-input": "required name=search_term_string",
    },
  };

  return (
    <div className="py-6 sm:py-8">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(siteJsonLd).replace(/</g, "\\u003c") }}
      />
      {/* Отметка визита: cookie для блока «новое с прошлого визита» */}
      <VisitStamp />
      {/* Сводка архива: две строки, чтобы медиа попадало в первый экран */}
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h1 className="dredge-title">архив // новое</h1>
        <span className="font-mono text-[11px] text-text-muted">
          {formatNumber(status.files_total)} файлов · {formatNumber(status.threads_active)} тредов ·{" "}
          {/* Отчётные сутки по МСК: +N с 00:00 — тот же период, что в админке и письме */}
          <span title={status.period_label || "отчётные сутки (МСК)"}>
            +{formatNumber(status.files_today)} за сутки
          </span>
        </span>
      </div>

      {/* «Новое с прошлого визита» — главный триггер вернуться (cookie dv_last) */}
      {lastVisit && freshCount > 0 ? (
        <TrackedLink
          href={`/new?since=${encodeURIComponent(lastVisit.toISOString())}`}
          event="new_since_click"
          className="mb-3 inline-flex items-center gap-1.5 rounded border border-accent-primary/50 bg-accent-primary/10 px-2.5 py-1 font-mono text-[11px] text-accent-primary transition-colors duration-150 hover:border-accent-primary hover:bg-accent-primary/20"
        >
          +{formatNumber(freshCount)}{" "}
          {plural(freshCount, ["новый файл", "новых файла", "новых файлов"])} с{" "}
          {visitLabel(lastVisit)} →
        </TrackedLink>
      ) : null}

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
        emptyHint="Новые файлы появятся здесь автоматически."
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
