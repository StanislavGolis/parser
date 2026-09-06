import type { Metadata } from "next";
import { notFound } from "next/navigation";

import AccessGate from "@/components/AccessGate";
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
  let accessRequired = false;
  try {
    list = await getBoardThreads(slug, 1, PER_PAGE);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    if (err instanceof ApiError && err.status === 403) {
      accessRequired = true;
    } else {
      throw err;
    }
  }

  return (
    <div className="container-site py-6 sm:py-8">
      <BoardHeader board={board} slug={slug} threadsTotal={list.total} />
      {accessRequired ? (
        <AccessGate slug={slug} title={board?.title} description={board?.description} />
      ) : (
        <BoardThreads slug={slug} initial={list} />
      )}
    </div>
  );
}

function BoardHeader({ board, slug, threadsTotal }: { board?: Board; slug: string; threadsTotal: number }) {
  return (
    <div className="mb-6">
      <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight sm:text-3xl">
        /{slug}
        {board?.title ? <span className="font-normal text-neutral-500">{board.title}</span> : null}
      </h1>
      {board?.description ? (
        <p className="mt-1 max-w-xl text-sm text-neutral-500">{board.description}</p>
      ) : null}
      <p className="mt-2 text-sm text-neutral-400">
        {formatNumber(threadsTotal)} {plural(threadsTotal, ["тред", "треда", "тредов"])}
      </p>
    </div>
  );
}
