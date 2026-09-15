import type { Metadata } from "next";
import { notFound } from "next/navigation";

import BoardThreads from "@/components/BoardThreads";
import { LockIcon, StarIcon } from "@/components/icons";
import { ApiError } from "@/lib/api";
import { getBoardThreads, getBoards } from "@/lib/data";
import { SITE_URL } from "@/lib/env";
import { formatNumber, plural } from "@/lib/format";
import { breadcrumbList, jsonLdHtml } from "@/lib/jsonld";
import type { Board, ThreadList } from "@/lib/types";

export const dynamic = "force-dynamic";

const PER_PAGE = 15;

interface BoardPageProps {
  params: { slug: string };
  searchParams: { sort?: string | string[]; thread?: string | string[] };
}

export async function generateMetadata({ params }: BoardPageProps): Promise<Metadata> {
  const board = await getBoards();
  const current = board.find((b) => b.slug === params.slug);
  // Скрытый/несуществующий раздел: 404 из метаданных — статус уходит до
  // стриминга страницы (иначе Next отдаёт «мягкий» 200, а это плохо для поиска).
  if (!current) notFound();
  // Название добавляем, только если оно не повторяет слаг: иначе в выдаче выходило
  // «/e — e» (у разделов, где нет отдельного имени).
  const named =
    Boolean(current.title) && current.title !== current.slug && current.title !== `/${current.slug}`;
  const title = named ? `/${current.slug} — ${current.title}` : `/${current.slug}`;
  const files = current.media_count ? `${formatNumber(current.media_count)} файлов — ` : "";
  return {
    title,
    description: `Раздел /${current.slug}: ${files}фото и видео в архиве, треды, превью и оригиналы файлов.`,
    alternates: { canonical: `/board/${current.slug}` },
    // Возрастная метка: контент раздела 18+
    other: { rating: "adult" },
  };
}

export default async function BoardPage({ params, searchParams }: BoardPageProps) {
  const { slug } = params;
  // `?sort=files` — порядок тредов по числу файлов (плюс варианты posts/views)
  const rawSort = Array.isArray(searchParams?.sort) ? searchParams.sort[0] : searchParams?.sort;
  const sort = ["new", "files", "posts", "views"].includes(rawSort ?? "") ? String(rawSort) : "new";
  // `?thread=…` — пришли по ссылке из ленты/меток/топа: открываем этот тред
  const rawThread = Array.isArray(searchParams?.thread) ? searchParams.thread[0] : searchParams?.thread;
  const threadId = rawThread && /^\d+$/.test(String(rawThread)) ? Number(rawThread) : null;

  const [boards] = await Promise.all([getBoards()]);
  const board = boards.find((b) => b.slug === slug);

  let list: ThreadList = { items: [], page: 1, per_page: PER_PAGE, total: 0 };
  try {
    list = await getBoardThreads(slug, 1, PER_PAGE, sort);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  // Микроразметка раздела: цепочка навигации + коллекция тредов (они кликабельны
  // и ведут на /board/{slug}?thread=…). isAccessibleForFree отражает премиум-гейт.
  const jsonLd = [
    breadcrumbList([
      { name: "Главная", path: "/" },
      { name: "Разделы", path: "/boards" },
      { name: `/${slug}`, path: `/board/${slug}` },
    ]),
    {
      "@context": "https://schema.org",
      "@type": "CollectionPage",
      name: board
        ? board.title && board.title !== slug && board.title !== `/${slug}`
          ? `/${slug} — ${board.title}`
          : `/${slug}`
        : `Раздел /${slug}`,
      description: board?.description ?? undefined,
      url: `${SITE_URL}/board/${slug}`,
      inLanguage: "ru-RU",
      isAccessibleForFree: !board?.locked,
      ...(list.items.length
        ? {
            mainEntity: {
              "@type": "ItemList",
              numberOfItems: list.total,
              itemListElement: list.items.map((thread, index) => ({
                "@type": "ListItem",
                position: index + 1,
                name: thread.subject?.trim() || `Тред №${thread.thread_id}`,
                url: `${SITE_URL}/board/${slug}?thread=${thread.thread_id}`,
              })),
            },
          }
        : {}),
    },
  ];

  return (
    <div className="py-6 sm:py-8">
      <script
        type="application/ld+json"
        // JSON-LD: сериализуем объект, экранируя «<», чтобы нельзя было вставить тег
        dangerouslySetInnerHTML={{ __html: jsonLdHtml(jsonLd) }}
      />
      <BoardHeader board={board} slug={slug} threadsTotal={list.total} />
      <BoardThreads slug={slug} initial={list} sort={sort} initialThreadId={threadId} />
    </div>
  );
}

function BoardHeader({ board, slug, threadsTotal }: { board?: Board; slug: string; threadsTotal: number }) {
  // В заголовке — человеческое название («Тиктокерши»), а адрес уходит тихой
  // сноской: читателю нужнее имя раздела, чем «/tiktokershi». Если имени нет,
  // заголовком остаётся адрес — пустого места на странице не будет.
  const human = board?.title?.trim();
  const named = Boolean(human) && human !== slug && human !== `/${slug}`;
  const title = named && human ? human : `/${slug}`;
  return (
    <div className="mb-6 border-b border-line pb-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-lg font-semibold text-text-primary" title={title}>
          {title}
        </h1>
        {named ? <span className="font-mono text-[11px] text-text-muted">/{slug}</span> : null}
        {board?.is_premium ? (
          <span
            className="badge badge-warn"
            title={
              board.locked
                ? "Премиум-раздел: нужна подписка"
                : "Премиум-раздел: доступен по вашей подписке"
            }
          >
            {board.locked ? (
              <LockIcon className="h-2.5 w-2.5" />
            ) : (
              <StarIcon className="h-2.5 w-2.5" />
            )}
            premium
          </span>
        ) : null}
      </div>
      {board?.description ? (
        <p className="mt-1 max-w-xl text-sm text-text-secondary">{board.description}</p>
      ) : null}
      {board?.is_premium ? (
        <p className="mt-1 max-w-xl text-xs text-accent-warning">
          {board.locked
            ? "Контент раздела доступен по премиум-подписке."
            : "Контент раздела доступен по вашей подписке."}
        </p>
      ) : null}
      <p className="mt-2 font-mono text-[11px] text-text-muted">
        {formatNumber(threadsTotal)} {plural(threadsTotal, ["тред", "треда", "тредов"])}
      </p>
    </div>
  );
}
