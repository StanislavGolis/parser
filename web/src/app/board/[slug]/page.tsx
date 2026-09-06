import type { Metadata } from "next";
import { notFound } from "next/navigation";

import AccessGate from "@/components/AccessGate";
import Gallery from "@/components/Gallery";
import QueryTabs from "@/components/QueryTabs";
import { ApiError } from "@/lib/api";
import { getBoardMediaPage, getBoards } from "@/lib/data";
import { formatNumber, plural } from "@/lib/format";
import type { Board, MediaList, MediaType, SortKey } from "@/lib/types";

export const dynamic = "force-dynamic";

const PER_PAGE = 30;

const TYPE_OPTIONS = [
  { value: "", label: "Всё" },
  { value: "image", label: "Картинки" },
  { value: "video", label: "Видео" },
];

const SORT_OPTIONS = [
  { value: "new", label: "Сначала новые" },
  { value: "popular", label: "По популярности" },
];

function mediaType(value?: string | string[]): MediaType | null {
  const v = Array.isArray(value) ? value[0] : value;
  return v === "image" || v === "video" ? v : null;
}

function sortKey(value?: string | string[]): SortKey {
  const v = Array.isArray(value) ? value[0] : value;
  return v === "popular" ? "popular" : "new";
}

interface BoardPageProps {
  params: { slug: string };
  searchParams: { sort?: string | string[]; type?: string | string[] };
}

export async function generateMetadata({ params }: BoardPageProps): Promise<Metadata> {
  const boards = await getBoards();
  const board = boards.find((b) => b.slug === params.slug);
  return {
    title: board ? `/${board.slug} — ${board.title ?? board.slug}` : `Раздел /${params.slug}`,
  };
}

export default async function BoardPage({ params, searchParams }: BoardPageProps) {
  const { slug } = params;
  const sort = sortKey(searchParams?.sort);
  const type = mediaType(searchParams?.type);

  const [boards] = await Promise.all([getBoards()]);
  const board = boards.find((b) => b.slug === slug);

  let list: MediaList = { items: [], page: 1, per_page: PER_PAGE, total: 0 };
  let accessRequired = false;
  try {
    list = await getBoardMediaPage(slug, sort, 1, PER_PAGE, type);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    // 403 на разделе = нужен код доступа (список досок может быть
    // устаревшим из Data Cache, поэтому полагаемся на ответ API).
    if (err instanceof ApiError && err.status === 403) {
      accessRequired = true;
    } else {
      throw err;
    }
  }

  const boardsById = Object.fromEntries(boards.map((b) => [b.id, b]));

  return (
    <div className="container-site py-6 sm:py-8">
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight sm:text-3xl">
            /{slug}
            {board?.title ? <span className="font-normal text-neutral-500">{board.title}</span> : null}
          </h1>
          {board?.description ? (
            <p className="mt-1 max-w-xl text-sm text-neutral-500">{board.description}</p>
          ) : null}
        </div>
      </div>

      {accessRequired ? (
        <AccessGate slug={slug} title={board?.title} description={board?.description} />
      ) : (
        <BoardContent
          board={board}
          slug={slug}
          list={list}
          type={type}
          sort={sort}
          boardsById={boardsById}
        />
      )}
    </div>
  );
}

/** Обычное содержимое раздела (сортировка/тип/галерея) — вынесено для читаемости. */
function BoardContent({
  board,
  slug,
  list,
  type,
  sort,
  boardsById,
}: {
  board?: Board;
  slug: string;
  list: MediaList;
  type: MediaType | null;
  sort: SortKey;
  boardsById: Record<number, Board>;
}) {
  return (
    <>
      {board?.is_private ? null : (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <QueryTabs param="sort" options={SORT_OPTIONS} defaultValue="new" ariaLabel="Сортировка" />
          <QueryTabs param="type" options={TYPE_OPTIONS} defaultValue="" ariaLabel="Тип контента" />
        </div>
      )}
      <div className="mb-4 text-sm text-neutral-400">
        {formatNumber(list.total)} {plural(list.total, ["файл", "файла", "файлов"])}
        {board ? (
          <span className="ml-2 text-xs text-neutral-600">из {formatNumber(board.media_count)} в разделе</span>
        ) : null}
      </div>

      <Gallery
        key={`board-${slug}-${sort}-${type ?? "all"}`}
        initial={list}
        apiPath={`/api/v1/boards/${encodeURIComponent(slug)}/media`}
        params={{ sort, ...(type ? { type } : {}) }}
        perPage={PER_PAGE}
        boardsById={boardsById}
        emptyTitle="В этом разделе пока пусто"
        emptyHint="Файлы появятся после следующего прохода парсера."
      />
    </>
  );
}
