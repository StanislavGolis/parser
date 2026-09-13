// Страница треда `/t/{thread_id}` — посадочная под поисковый запрос.
//
// У треда единственный в архиве осмысленный текст (тема и описание записи у
// сайтов, тема треда у 2ch), поэтому у него свой адрес и своя разметка:
// без этого поисковику не за что зацепиться, а ленте раздела приходится
// отвечать сразу за все треды.
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import Gallery from "@/components/Gallery";
import When from "@/components/When";
import {
  ArrowLeftIcon,
  EyeIcon,
  ImageIcon,
  LockIcon,
  StarIcon,
} from "@/components/icons";
import { getBoardMediaPage, getBoardThreads, getThreadDetail } from "@/lib/data";
import { SITE_URL, absoluteUrl } from "@/lib/env";
import { formatNumber, plural } from "@/lib/format";
import { breadcrumbList, jsonLdHtml } from "@/lib/jsonld";
import type { ThreadDetail, ThreadList } from "@/lib/types";

export const dynamic = "force-dynamic";

/** Файлов на первую страницу галереи (остальное — догрузка при скролле). */
const PER_PAGE = 30;
/** Других тредов раздела в блоке перелинковки. */
const MORE_THREADS = 8;
/** Сколько символов описания треда показываем на странице. */
const COMMENT_LIMIT = 1200;

const EMPTY_THREADS: ThreadList = { items: [], page: 1, per_page: MORE_THREADS, total: 0 };

interface ThreadPageProps {
  params: { id: string };
}

/**
 * Номер треда из адреса: поддерживаем и `/t/123`, и `/t/123-тема-треда`.
 * Хвост после дефиса — только для читаемости ссылки; канонический вид — `/t/123`.
 */
function parseThreadId(raw: string): number {
  const match = /^(\d{1,12})/.exec(decodeURIComponent(raw));
  if (!match) return Number.NaN;
  const value = Number(match[1]);
  return Number.isFinite(value) && value > 0 ? value : Number.NaN;
}

function threadTitle(thread: ThreadDetail): string {
  return thread.subject?.trim() || `Тред №${thread.thread_id}`;
}

/** Описание страницы: текст записи, иначе — сводка по файлам треда. */
function threadDescription(thread: ThreadDetail): string {
  const comment = (thread.comment ?? "").replace(/\s+/g, " ").trim();
  if (comment) return comment.length > 300 ? `${comment.slice(0, 300)}…` : comment;
  const files = `${formatNumber(thread.media_total)} ${plural(thread.media_total, ["файл", "файла", "файлов"])}`;
  return `${threadTitle(thread)} — ${files} в архиве раздела /${thread.board_slug}.`;
}

export async function generateMetadata({ params }: ThreadPageProps): Promise<Metadata> {
  const id = parseThreadId(params.id);
  if (!Number.isFinite(id)) notFound();

  const thread = await getThreadDetail(id).catch(() => null);
  // notFound() именно здесь: так 404 уходит до стриминга страницы, иначе
  // Next отдал бы «мягкий» 200 для несуществующего или скрытого треда.
  if (!thread) notFound();

  const title = threadTitle(thread);
  const description = threadDescription(thread);
  // Превью для соцсетей: первый файл треда (обычно обложка записи).
  const first = await getBoardMediaPage(thread.board_slug, "new", 1, 1, null, thread.thread_id)
    .catch(() => null);
  const preview = first?.items[0];
  const image = preview ? absoluteUrl(preview.web_url ?? preview.thumb_url) : undefined;

  return {
    title,
    description,
    alternates: { canonical: `/t/${thread.thread_id}` },
    // Файлы архива 18+
    other: { rating: "adult" },
    openGraph: {
      title,
      description,
      type: "website",
      ...(image ? { images: [image] } : {}),
    },
  };
}

export default async function ThreadPage({ params }: ThreadPageProps) {
  const id = parseThreadId(params.id);
  if (!Number.isFinite(id)) notFound();

  const thread = await getThreadDetail(id);
  if (!thread) notFound();

  const [first, others] = await Promise.all([
    getBoardMediaPage(thread.board_slug, "new", 1, PER_PAGE, null, thread.thread_id),
    getBoardThreads(thread.board_slug, 1, MORE_THREADS + 1, "new").catch(() => EMPTY_THREADS),
  ]);

  const title = threadTitle(thread);
  const neighbours = others.items
    .filter((item) => item.thread_id !== thread.thread_id)
    .slice(0, MORE_THREADS);
  const canonical = `/t/${thread.thread_id}`;

  const jsonLd = [
    breadcrumbList([
      { name: "Главная", path: "/" },
      { name: "Разделы", path: "/boards" },
      { name: `/${thread.board_slug}`, path: `/board/${thread.board_slug}` },
      { name: title, path: canonical },
    ]),
    {
      "@context": "https://schema.org",
      "@type": "CollectionPage",
      name: title,
      url: `${SITE_URL}${canonical}`,
      ...(thread.comment ? { description: thread.comment.slice(0, 300) } : {}),
      ...(first.items.length
        ? {
            mainEntity: {
              "@type": "ItemList",
              numberOfItems: first.total,
              itemListElement: first.items.map((media, index) => ({
                "@type": "ListItem",
                position: index + 1,
                name: media.original_name,
                url: `${SITE_URL}/media/${media.id}`,
              })),
            },
          }
        : {}),
    },
  ];

  return (
    <div className="container-site py-6 sm:py-8">
      <script
        type="application/ld+json"
        // JSON-LD: сериализуем объект, экранируя «<», чтобы нельзя было вставить тег
        dangerouslySetInnerHTML={{ __html: jsonLdHtml(jsonLd) }}
      />

      <nav
        aria-label="Хлебные крошки"
        className="mb-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-neutral-400"
      >
        <Link href="/" className="transition-colors hover:text-white">
          Главная
        </Link>
        <span className="text-neutral-600">/</span>
        <Link href="/boards" className="transition-colors hover:text-white">
          Разделы
        </Link>
        <span className="text-neutral-600">/</span>
        <Link
          href={`/board/${thread.board_slug}`}
          className="font-mono transition-colors hover:text-white"
        >
          /{thread.board_slug}
        </Link>
        <span className="text-neutral-600">/</span>
        <span className="font-mono text-neutral-500">№{thread.thread_id}</span>
      </nav>

      <header className="mb-5 border-b border-line pb-4">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-lg font-semibold text-text-primary">{title}</h1>
          {thread.is_premium ? (
            <span
              className="badge badge-warn"
              title={
                thread.locked
                  ? "Премиум-тред: нужна подписка"
                  : "Премиум-тред: доступен по вашей подписке"
              }
            >
              {thread.locked ? (
                <LockIcon className="h-2.5 w-2.5" />
              ) : (
                <StarIcon className="h-2.5 w-2.5" />
              )}
              premium
            </span>
          ) : null}
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-text-muted">
          <span>№{thread.thread_id}</span>
          <span className="inline-flex items-center gap-1" title="Файлов треда в архиве">
            <ImageIcon className="h-3 w-3" />
            {formatNumber(thread.media_total)}{" "}
            {plural(thread.media_total, ["файл", "файла", "файлов"])}
          </span>
          {thread.views_count ? (
            <span className="inline-flex items-center gap-1" title="Просмотров треда у источника">
              <EyeIcon className="h-3 w-3" />
              {formatNumber(thread.views_count)}
            </span>
          ) : null}
          {thread.last_media_at || thread.thread_timestamp ? (
            <When iso={(thread.last_media_at ?? thread.thread_timestamp) as string} />
          ) : null}
        </div>

        {thread.is_premium ? (
          <p className="mt-1 text-xs text-accent-warning">
            {thread.locked
              ? "Контент треда доступен по премиум-подписке."
              : "Контент треда доступен по вашей подписке."}
          </p>
        ) : null}

        {thread.comment ? (
          <p className="mt-2 max-w-3xl whitespace-pre-line text-sm leading-relaxed text-text-secondary">
            {thread.comment.slice(0, COMMENT_LIMIT)}
          </p>
        ) : null}
      </header>

      {/* Файлы треда: та же галерея с догрузкой, что и в разделе */}
      <Gallery
        initial={first}
        apiPath={`/api/v1/boards/${encodeURIComponent(thread.board_slug)}/media`}
        params={{ thread: String(thread.thread_id) }}
        perPage={PER_PAGE}
        emptyTitle="В этом треде пока нет файлов"
        emptyHint="Файлы появятся здесь после следующего прохода парсера."
      />

      {/* Перелинковка: соседние треды раздела — ссылки для людей и роботов */}
      {neighbours.length ? (
        <section className="mt-8">
          <h2 className="mb-3 font-mono text-[11px] uppercase tracking-wider text-text-muted">
            другие треды раздела /{thread.board_slug}
          </h2>
          <ul className="flex flex-col gap-2">
            {neighbours.map((item) => (
              <li key={item.thread_id}>
                <Link
                  href={`/t/${item.thread_id}`}
                  className="flex items-center justify-between gap-3 rounded border border-line bg-ink-secondary px-3 py-2 text-sm text-text-primary transition-colors hover:border-accent-primary"
                >
                  <span className="truncate">
                    {item.subject?.trim() || `Тред №${item.thread_id}`}
                  </span>
                  <span className="shrink-0 font-mono text-[11px] text-text-muted">
                    {formatNumber(item.media_visible)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <div className="mt-3">
            <Link
              href={`/board/${thread.board_slug}`}
              className="inline-flex items-center gap-1.5 text-sm text-neutral-400 transition-colors hover:text-white"
            >
              <ArrowLeftIcon className="h-4 w-4" />
              все треды раздела /{thread.board_slug}
            </Link>
          </div>
        </section>
      ) : null}
    </div>
  );
}
