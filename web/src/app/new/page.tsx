import type { Metadata } from "next";
import Link from "next/link";

import Gallery from "@/components/Gallery";
import QueryTabs from "@/components/QueryTabs";
import { getBoards, getFeedPage } from "@/lib/data";
import { formatNumber, plural } from "@/lib/format";
import type { MediaType } from "@/lib/types";
import { parseVisitDate, visitLabel } from "@/lib/visit";

export const dynamic = "force-dynamic";

const PER_PAGE = 30;

const TYPE_OPTIONS = [
  { value: "", label: "Всё" },
  { value: "image", label: "Картинки" },
  { value: "video", label: "Видео" },
];

function mediaType(value?: string | string[]): MediaType | null {
  const v = Array.isArray(value) ? value[0] : value;
  return v === "image" || v === "video" ? v : null;
}

export const metadata: Metadata = {
  title: "Новинки",
  description:
    "Полный поток свежих файлов архива: новые фото и видео, фильтры по типу, автоподгрузка. Обновляется постоянно.",
  alternates: { canonical: "/new" },
};

export default async function NewPage({
  searchParams,
}: {
  searchParams: { type?: string | string[]; since?: string | string[] };
}) {
  const type = mediaType(searchParams?.type);
  // `since` приходит из блока «новое с прошлого визита» на главной.
  const rawSince = Array.isArray(searchParams?.since) ? searchParams.since[0] : searchParams?.since;
  const since = parseVisitDate(rawSince);

  const [feed, boards] = await Promise.all([
    getFeedPage(1, PER_PAGE, type, false, since?.toISOString()),
    getBoards(),
  ]);
  const boardsById = Object.fromEntries(boards.map((b) => [b.id, b]));

  const heading =
    type === "image" ? "новые картинки" : type === "video" ? "новые видео" : "новинки";

  return (
    <div className="py-6 sm:py-8">
      <div className="mb-2 flex flex-wrap items-end justify-between gap-3">
        <h1 className="dredge-title">новое // {heading}</h1>
        <span className="font-mono text-[11px] text-text-muted">
          {formatNumber(feed.total)} {plural(feed.total, ["файл", "файла", "файлов"])}
        </span>
      </div>
      {since ? (
        <p className="mb-2 font-mono text-[11px] text-text-muted">
          с прошлого визита: всё, что появилось после {visitLabel(since)} ·{" "}
          <Link href="/new" className="text-accent-primary hover:underline">
            показать весь поток
          </Link>
        </p>
      ) : null}
      <div className="mb-5">
        <QueryTabs param="type" options={TYPE_OPTIONS} defaultValue="" ariaLabel="Тип контента" />
      </div>

      <Gallery
        key={`feed-${type ?? "all"}-${since ? since.toISOString() : "all"}`}
        initial={feed}
        apiPath="/api/v1/feed"
        params={{ ...(type ? { type } : {}), ...(since ? { since: since.toISOString() } : {}) }}
        perPage={PER_PAGE}
        boardsById={boardsById}
        emptyTitle={since ? "С прошлого визита новинок нет" : "Пока нет файлов"}
        emptyHint={
          since
            ? "Всё уже просмотрено — заглядывайте позже, архив пополняется."
            : "Новые файлы появятся здесь автоматически."
        }
      />
    </div>
  );
}
