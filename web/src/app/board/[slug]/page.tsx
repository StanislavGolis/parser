import type { Metadata } from "next";
import { notFound } from "next/navigation";

import BoardThreads from "@/components/BoardThreads";
import { ApiError } from "@/lib/api";
import { getBoardThreads, getBoards } from "@/lib/data";
import { formatNumber, plural } from "@/lib/format";
import type { Board, ThreadList } from "@/lib/types";

export const dynamic = "force-dynamic";

const PER_PAGE = 15;

interface BoardPageProps {
  params: { slug: string };
}

export async function generateMetadata({ params }: BoardPageProps): Promise<Metadata> {
  const boards = await getBoards();
  const board = boards.find((b) => b.slug === params.slug);
  return {
    title: board ? `/${board.slug} — ${board.title ?? board.slug}` : `Раздел /${params.slug}`,
  };
}

export default async function BoardPage({ params }: BoardPageProps) {
  const { slug } = params;

  const [boards] = await Promise.all([getBoards()]);
  const board = boards.find((b) => b.slug === slug);

  let list: ThreadList = { items: [], page: 1, per_page: PER_PAGE, total: 0 };
  try {
    list = await getBoardThreads(slug, 1, PER_PAGE);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  return (
    <div className="py-6 sm:py-8">
      <BoardHeader board={board} slug={slug} threadsTotal={list.total} />
      <BoardThreads slug={slug} initial={list} />
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
        {board?.is_premium ? <span className="badge badge-warn">premium</span> : null}
      </div>
      {board?.description ? (
        <p className="mt-1 max-w-xl text-sm text-text-secondary">{board.description}</p>
      ) : null}
      {board?.is_premium ? (
        <p className="mt-1 max-w-xl text-xs text-accent-warning">
          Контент раздела доступен по премиум-подписке: превью размыты, полные файлы скрыты.
        </p>
      ) : null}
      <p className="mt-2 font-mono text-[11px] text-text-muted">
        {formatNumber(threadsTotal)} {plural(threadsTotal, ["тред", "треда", "тредов"])}
      </p>
    </div>
  );
}
