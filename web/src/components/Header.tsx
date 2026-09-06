import Link from "next/link";

import { getBoards } from "@/lib/data";
import { formatNumber } from "@/lib/format";

/**
 * Шапка сайта: навигация «Новинки / Популярное» + разделы (доски).
 * Серверный компонент: доски берутся из API с Data Cache и отдаются в HTML
 * (важно для SEO и видимости разделов).
 */
export default async function Header() {
  const boards = await getBoards();

  return (
    <header className="sticky top-0 z-40 border-b border-neutral-800 bg-neutral-950/90 backdrop-blur">
      <div className="container-site flex h-14 items-center justify-between gap-4">
        <Link href="/" className="flex shrink-0 items-baseline gap-2" aria-label="На главную">
          <span className="text-lg font-bold tracking-tight text-amber-400">Галерея</span>
          <span className="hidden text-xs text-neutral-500 sm:inline">медиа с имиджборд</span>
        </Link>

        <nav className="flex items-center gap-1 text-sm font-medium">
          <Link href="/" className="rounded-md px-3 py-1.5 text-neutral-300 transition-colors hover:bg-neutral-800 hover:text-white">
            Новинки
          </Link>
          <Link
            href="/top"
            className="rounded-md px-3 py-1.5 text-neutral-300 transition-colors hover:bg-neutral-800 hover:text-white"
          >
            Популярное
          </Link>
        </nav>
      </div>

      {boards.length > 0 && (
        <div className="container-site flex items-center gap-2 overflow-x-auto border-t border-neutral-800/70 py-2 [scrollbar-width:thin]">
          <span className="shrink-0 text-xs uppercase tracking-wider text-neutral-500">Разделы</span>
          {boards.map((b) => (
            <Link
              key={b.id}
              href={`/board/${b.slug}`}
              className="flex shrink-0 items-center gap-1.5 rounded-full border border-neutral-700 bg-neutral-900 px-3 py-1 text-xs text-neutral-200 transition-colors hover:border-amber-500/60 hover:text-amber-300"
            >
              <span className="font-semibold">/{b.slug}</span>
              <span className="max-w-28 truncate text-neutral-400">{b.title}</span>
              <span className="rounded bg-neutral-800 px-1.5 text-[10px] text-neutral-400">
                {formatNumber(b.media_count)}
              </span>
            </Link>
          ))}
        </div>
      )}
    </header>
  );
}
