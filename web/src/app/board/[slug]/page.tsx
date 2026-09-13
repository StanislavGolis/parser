import type { Metadata } from "next";
import { notFound } from "next/navigation";

import BoardThreads from "@/components/BoardThreads";
import { LockIcon, StarIcon } from "@/components/icons";
import { ApiError } from "@/lib/api";
import { getBoardThreads, getBoards } from "@/lib/data";
import { formatNumber, plural } from "@/lib/format";
import type { Board, ThreadList } from "@/lib/types";

export const dynamic = "force-dynamic";

const PER_PAGE = 15;

interface BoardPageProps {
  params: { slug: string };
  searchParams: { sort?: string | string[]; thread?: string | string[] };
}

export async function generateMetadata({ params }: BoardPageProps): Promise<Metadata> {
  const boards = await getBoards();
  const board = boards.find((b) => b.slug === params.slug);
  const title = board ? `/${board.slug} — ${board.title ?? board.slug}` : `Раздел /${params.slug}`;
  const files = board?.media_count ? `${formatNumber(board.media_count)} файлов — ` : "";
  return {
    title,
    description: `Раздел /${params.slug}: ${files}фото и видео в архиве, треды, превью и оригиналы файлов.`,
    alternates: { canonical: `/board/${params.slug}` },
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

  return (
    <div className="py-6 sm:py-8">
      <BoardHeader board={board} slug={slug} threadsTotal={list.total} />
      <BoardThreads slug={slug} initial={list} sort={sort} initialThreadId={threadId} />
    </div>
  );
}

function BoardHeader({ board, slug, threadsTotal }: { board?: Board; slug: string; threadsTotal: number }) {
  return (
    <div className="mb-6 border-b border-line pb-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="font-mono text-lg font-bold uppercase tracking-[0.12em] text-text-primary">
          /{slug}
        </h1>
        {board?.title ? <span className="text-sm text-text-secondary">— {board.title}</span> : null}
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
            ? "Контент раздела доступен по премиум-подписке: превью размыты, полные файлы скрыты."
            : "Премиум-раздел: ваша подписка активна — полные файлы доступны."}
        </p>
      ) : null}
      <p className="mt-2 font-mono text-[11px] text-text-muted">
        {formatNumber(threadsTotal)} {plural(threadsTotal, ["тред", "треда", "тредов"])}
      </p>
    </div>
  );
}
