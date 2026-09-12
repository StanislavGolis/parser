import type { Metadata } from "next";

import Gallery from "@/components/Gallery";
import QueryTabs from "@/components/QueryTabs";
import { getBoards, getFeedPage } from "@/lib/data";
import { formatNumber, plural } from "@/lib/format";
import type { MediaType } from "@/lib/types";

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
  searchParams: { type?: string | string[] };
}) {
  const type = mediaType(searchParams?.type);

  const [feed, boards] = await Promise.all([getFeedPage(1, PER_PAGE, type), getBoards()]);
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
      <div className="mb-5">
        <QueryTabs param="type" options={TYPE_OPTIONS} defaultValue="" ariaLabel="Тип контента" />
      </div>

      <Gallery
        key={`feed-${type ?? "all"}`}
        initial={feed}
        apiPath="/api/v1/feed"
        params={type ? { type } : {}}
        perPage={PER_PAGE}
        boardsById={boardsById}
        emptyTitle="Пока нет файлов"
        emptyHint="Новые файлы появятся здесь автоматически."
      />
    </div>
  );
}
