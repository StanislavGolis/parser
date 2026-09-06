import type { Metadata } from "next";

import Gallery from "@/components/Gallery";
import SearchBox from "@/components/SearchBox";
import { getBoards, getSearchPage } from "@/lib/data";
import { formatNumber, plural } from "@/lib/format";
import type { BoardsById, MediaList } from "@/lib/types";

export const dynamic = "force-dynamic";

const PER_PAGE = 30;

export const metadata: Metadata = {
  title: "Поиск",
};

export default async function SearchPage({
  searchParams,
}: {
  searchParams: { q?: string | string[] };
}) {
  const raw = Array.isArray(searchParams?.q) ? searchParams.q[0] : searchParams?.q;
  const q = (raw ?? "").trim();

  let list: MediaList = { items: [], page: 1, per_page: PER_PAGE, total: 0 };
  let boardsById: BoardsById = {};

  if (q.length >= 2) {
    const [res, boards] = await Promise.all([getSearchPage(q, 1, PER_PAGE), getBoards()]);
    list = res;
    boardsById = Object.fromEntries(boards.map((b) => [b.id, b]));
  }

  return (
    <div className="py-6 sm:py-8">
      <h1 className="sluice-title mb-1">поиск // файлы</h1>
      <p className="mb-5 text-sm text-text-secondary">
        Ищем по имени файла, MD5 или SHA-256. Минимум 2 символа.
      </p>

      <div className="mb-6">
        <SearchBox initial={q} />
      </div>

      {q.length < 2 ? (
        <p className="py-16 text-center font-mono text-[11px] uppercase tracking-widest text-text-muted">
          введите запрос для поиска по архиву
        </p>
      ) : (
        <>
          <p className="mb-4 font-mono text-[11px] text-text-muted">
            «{q}» · {formatNumber(list.total)}{" "}
            {plural(list.total, ["совпадение", "совпадения", "совпадений"])}
          </p>
          {list.total === 0 ? (
            <p className="py-16 text-center text-sm text-text-secondary">
              Ничего не найдено. Попробуйте другое имя, md5 или sha-256.
            </p>
          ) : (
            <Gallery
              key={`search-${q}`}
              initial={list}
              apiPath="/api/v1/search"
              params={{ q }}
              perPage={PER_PAGE}
              boardsById={boardsById}
              emptyTitle="Ничего не найдено"
              emptyHint="Попробуйте изменить запрос."
            />
          )}
        </>
      )}
    </div>
  );
}
