import type { Metadata } from "next";

import BoardsCatalog from "@/components/BoardsCatalog";
import { getBoards } from "@/lib/data";
import { formatNumber } from "@/lib/format";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Разделы архива",
  description:
    "Каталог разделов архива: внутри каждого — треды и файлы, превью и оригиналы, свежие поступления и топ.",
  alternates: { canonical: "/boards" },
};

/** Каталог разделов-архивов (перенесён с главной: главная теперь — витрина новинок). */
export default async function BoardsPage() {
  const boards = await getBoards();
  const totalFiles = boards.reduce((sum, b) => sum + (b.media_count || 0), 0);

  return (
    <div className="py-6 sm:py-8">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="dredge-title">архив // доски</h1>
        <span className="font-mono text-[11px] text-text-muted">
          {formatNumber(boards.length)} досок · {formatNumber(totalFiles)} файлов
        </span>
      </div>
      <p className="mb-6 text-sm text-text-secondary">
        Разделы-архивы. Внутри каждого — треды и файлы с раздела.
      </p>

      <BoardsCatalog boards={boards} />
    </div>
  );
}
