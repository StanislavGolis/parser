import type { Metadata } from "next";
import { cookies } from "next/headers";
import Link from "next/link";

import Gallery from "@/components/Gallery";
import HidePremiumToggle from "@/components/HidePremiumToggle";
import QueryTabs from "@/components/QueryTabs";
import { getBoards, getFeedPage } from "@/lib/data";
import { formatNumber, plural } from "@/lib/format";
import { HIDE_PREMIUM_COOKIE, HIDE_PREMIUM_ON } from "@/lib/prefs";
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
  other: { rating: "adult" },
};

export default async function NewPage({
  searchParams,
}: {
  searchParams: { type?: string | string[]; since?: string | string[]; cursor?: string | string[] };
}) {
  const type = mediaType(searchParams?.type);
  // `since` приходит из блока «новое с прошлого визита» на главной.
  const rawSince = Array.isArray(searchParams?.since) ? searchParams.since[0] : searchParams?.since;
  const since = parseVisitDate(rawSince);
  // `cursor` приходит с кнопки «Дальше в потоке» на главной: продолжаем ленту с того
  // же места, а не показываем заново то, что зритель уже видел на витрине.
  const rawCursor = Array.isArray(searchParams?.cursor) ? searchParams.cursor[0] : searchParams?.cursor;
  const cursor = rawCursor?.trim() ? rawCursor.trim() : null;
  // «Скрыть премиум» — та же личная настройка, что в фильтрах главной (cookie).
  const hidePremium = cookies().get(HIDE_PREMIUM_COOKIE)?.value === HIDE_PREMIUM_ON;

  const [feed, boards] = await Promise.all([
    getFeedPage(1, PER_PAGE, type, hidePremium, since?.toISOString(), cursor),
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
      {cursor ? (
        <p className="mb-2 font-mono text-[11px] text-text-muted">
          продолжение потока — то, что было ниже на главной ·{" "}
          <Link href="/new" className="text-accent-primary hover:underline">
            с начала
          </Link>
        </p>
      ) : null}
      {since ? (
        <p className="mb-2 font-mono text-[11px] text-text-muted">
          с прошлого визита: всё, что появилось после {visitLabel(since)} ·{" "}
          <Link href="/new" className="text-accent-primary hover:underline">
            показать весь поток
          </Link>
        </p>
      ) : null}
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <QueryTabs param="type" options={TYPE_OPTIONS} defaultValue="" ariaLabel="Тип контента" />
        {/* Личная настройка: прячет премиум-файлы (cookie), см. HidePremiumToggle */}
        <HidePremiumToggle />
      </div>

      <Gallery
        key={`feed-${type ?? "all"}-${hidePremium ? "nopremium" : "all"}-${since ? since.toISOString() : "all"}-${cursor ?? "start"}`}
        initial={feed}
        apiPath="/api/v1/feed"
        params={{
          ...(type ? { type } : {}),
          ...(hidePremium ? { free: "1" } : {}),
          ...(since ? { since: since.toISOString() } : {}),
        }}
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
