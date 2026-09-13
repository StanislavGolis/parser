import type { Metadata } from "next";

import Gallery from "@/components/Gallery";
import QueryTabs from "@/components/QueryTabs";
import { getBoards, getTopMedia } from "@/lib/data";
import { formatNumber } from "@/lib/format";
import type { MediaItem, MediaList, MediaType, PeriodKey } from "@/lib/types";

export const dynamic = "force-dynamic";

const TOP_LIMIT = 60;

const PERIOD_OPTIONS = [
  { value: "day", label: "За день" },
  { value: "week", label: "За неделю" },
  { value: "month", label: "За месяц" },
];

const TYPE_OPTIONS = [
  { value: "", label: "Всё" },
  { value: "image", label: "Картинки" },
  { value: "video", label: "Видео" },
];

function mediaType(value?: string | string[]): MediaType | null {
  const v = Array.isArray(value) ? value[0] : value;
  return v === "image" || v === "video" ? v : null;
}

function period(value?: string | string[]): PeriodKey {
  const v = Array.isArray(value) ? value[0] : value;
  return v === "day" || v === "week" || v === "month" ? v : "day";
}

export function generateMetadata(): Metadata {
  return {
    title: "Топ файлов",
    description:
      "Самые популярные файлы архива: топ за день, неделю и месяц — по просмотрам и скачиваниям.",
    // Период и тип — параметры одного и того же топ-списка: канонизируем на /top.
    alternates: { canonical: "/top" },
    // Возрастная метка: файлы архива 18+
    other: { rating: "adult" },
  };
}

export default async function TopPage({
  searchParams,
}: {
  searchParams: { period?: string | string[]; type?: string | string[] };
}) {
  const p = period(searchParams?.period);
  const type = mediaType(searchParams?.type);

  const [items, boards] = await Promise.all([getTopMedia(p, type, TOP_LIMIT), getBoards()]);
  const boardsById = Object.fromEntries(boards.map((b) => [b.id, b]));

  // Популярное отдаётся одним срезом без пагинации — оборачиваем как одну «страницу».
  const topList: MediaList = {
    items: items as MediaItem[],
    page: 1,
    per_page: Math.max(items.length, 1),
    total: items.length,
  };

  const periodLabel: Record<PeriodKey, string> = { day: "день", week: "неделя", month: "месяц" };

  return (
    <div className="py-6 sm:py-8">
      <div className="mb-2 flex flex-wrap items-end justify-between gap-3">
        <h1 className="dredge-title">топ // {periodLabel[p]}</h1>
        <div className="flex flex-wrap items-center gap-2">
          <QueryTabs param="period" options={PERIOD_OPTIONS} defaultValue="day" ariaLabel="Период" />
          <QueryTabs param="type" options={TYPE_OPTIONS} defaultValue="" ariaLabel="Тип контента" />
        </div>
      </div>
      <p className="mb-6 text-sm text-text-secondary">
        самые просматриваемые файлы ·{" "}
        <span className="font-mono text-text-primary">{formatNumber(items.length)}</span>
      </p>

      <Gallery
        key={`top-${p}-${type ?? "all"}`}
        initial={topList}
        apiPath="/api/v1/top"
        params={{ period: p, ...(type ? { type } : {}) }}
        perPage={Math.max(items.length, 1)}
        boardsById={boardsById}
        showTop
        emptyTitle="Пока ничего не набрало просмотры"
        emptyHint="Загляните позже — статистика обновляется регулярно."
      />
    </div>
  );
}
