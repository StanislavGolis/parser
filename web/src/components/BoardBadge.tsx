import Link from "next/link";

import type { Board } from "@/lib/types";

/** Плитка-метка доски (используется в лентах «Новинки» и «Популярное»). */
export default function BoardBadge({
  board,
  className = "",
}: {
  board?: Board | null;
  className?: string;
}) {
  if (!board) return null;
  return (
    <Link
      href={`/board/${board.slug}`}
      title={board.title ?? board.slug}
      className={`inline-flex items-center gap-1 rounded-md bg-black/55 px-1.5 py-0.5 text-[11px] font-semibold text-amber-300 backdrop-blur-sm transition-colors hover:text-amber-200 ${className}`}
      onClick={(e) => e.stopPropagation()}
    >
      /{board.slug}
      {board.title ? <span className="hidden font-normal text-neutral-300 sm:inline">{board.title}</span> : null}
    </Link>
  );
}
