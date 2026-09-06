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

interface HomeProps {
  searchParams: { type?: string | string[] };
}

export function generateMetadata(): Metadata {
  return { title: "Новинки" };
}

export default async function HomePage({ searchParams }: HomeProps) {
  const type = mediaType(searchParams?.type);

  const [feed, boards] = await Promise.all([getFeedPage(1, PER_PAGE, type), getBoards()]);
  const boardsById = Object.fromEntries(boards.map((b) => [b.id, b]));

  const heading =
    type === "image" ? "Новые картинки" : type === "video" ? "Новые видео" : "Новинки";

  return (
    <div className="container-site py-6 sm:py-8">
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{heading}</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Последние файлы со всех разделов ·{" "}
            <span className="font-medium text-neutral-300">
              {formatNumber(feed.total)} {plural(feed.total, ["файл", "файла", "файлов"])}
            </span>
          </p>
        </div>
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
        emptyHint="Новые файлы появятся здесь после следующего прохода парсера."
      />
    </div>
  );
}
