"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { LayersIcon } from "@/components/icons";
import { mediaUrl } from "@/lib/env";
import { formatNumber } from "@/lib/format";
import type { Board } from "@/lib/types";
import { useImgLoaded } from "@/lib/useImgLoaded";

type Filter = "all" | "free" | "premium";
type View = "grid" | "list";

const FILTERS: Array<{ value: Filter; label: string }> = [
  { value: "all", label: "ВСЕ" },
  { value: "free", label: "БЕЗ ПОДПИСКИ" },
  { value: "premium", label: "ПРЕМИУМ" },
];

/** Вид каталога: плитки с обложками или компактный список. */
const VIEWS: Array<{ value: View; label: string }> = [
  { value: "grid", label: "плитки" },
  { value: "list", label: "список" },
];

const VIEW_KEY = "dv_boards_view";

/** Сколько превью в мозаике обложки (2×2). */
const MOSAIC_TILES = 4;

/**
 * Название раздела для заголовка карточки. Обычно это человеческое имя с сайта
 * («Тиктокерши»), а если его нет — слаг: тогда адрес и есть имя, дублировать нечего.
 */
function boardTitle(board: Board): string {
  const title = board.title?.trim();
  if (title && title !== board.slug && title !== `/${board.slug}`) return title;
  return board.slug;
}

/**
 * Пропорции обложки (ширина / высота). Одна константа на все карточки:
 * высота мозаики не зависит ни от размеров превью, ни от числа файлов
 * в разделе — подписи у всех карточек начинаются на одной линии.
 */
const COVER_ASPECT = "2 / 1";

/** Плитка обложки: пульсирующий скелетон → плавное появление превью. */
function CoverTile({ src, eager = false }: { src?: string; eager?: boolean }) {
  // Тот же приём, что и в карточках медиа: `complete` + таймаут, иначе плитка
  // из кэша навсегда осталась бы под скелетоном.
  const img = useImgLoaded(src ?? "", 1200);
  const showSkeleton = Boolean(src) && !img.loaded;

  return (
    // Картинка лежит абсолютно: её натуральные размеры не участвуют в раскладке,
    // поэтому все плитки (и вся мозаика) строго одной высоты.
    <span className="relative block h-full w-full overflow-hidden bg-ink-tertiary">
      {showSkeleton ? (
        <span className="absolute inset-0 animate-pulse bg-ink-tertiary" aria-hidden />
      ) : null}
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          ref={img.setRef}
          src={src}
          alt=""
          loading={eager ? "eager" : "lazy"}
          decoding="async"
          referrerPolicy="no-referrer"
          onLoad={img.onLoad}
          className={`absolute inset-0 h-full w-full object-cover transition-all duration-300 group-hover:scale-[1.04] ${
            img.loaded ? "opacity-100" : "opacity-0"
          }`}
        />
      ) : (
        <span className="absolute inset-0 bg-ink-secondary/40" aria-hidden />
      )}
    </span>
  );
}

/** Обложка раздела: мозаика 2×2 из свежих превью (до 4 плиток). */
function CoverMosaic({ board, eager = false }: { board: Board; eager?: boolean }) {
  const thumbs = (board.cover_thumbs ?? []).slice(0, MOSAIC_TILES);
  return (
    // Приглушаем обложку: она фон для названия, а не цель карточки
    <span
      className="grid w-full shrink-0 grid-cols-2 grid-rows-2 gap-px overflow-hidden border-b border-line bg-line opacity-90 transition-opacity group-hover:opacity-100"
      style={{ aspectRatio: COVER_ASPECT }}
      aria-hidden
    >
      {Array.from({ length: MOSAIC_TILES }, (_, i) => (
        <CoverTile key={i} src={mediaUrl(thumbs[i])} eager={eager} />
      ))}
    </span>
  );
}

/** Каталог разделов: карточка = мозаика свежих превью + имя и счётчик файлов. */
export default function BoardsCatalog({ boards }: { boards: Board[] }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [view, setView] = useState<View>("grid");

  // Вид каталога запоминаем: админ/посетитель, выбравший список, возвращается к списку
  useEffect(() => {
    const saved = window.localStorage.getItem(VIEW_KEY);
    if (saved === "grid" || saved === "list") setView(saved);
  }, []);

  function pickView(next: View) {
    setView(next);
    window.localStorage.setItem(VIEW_KEY, next);
  }

  // Автосортировка: разделы по количеству файлов, крупные — первыми. Сортировка
  // устойчивая, поэтому разделы с равным числом файлов остаются в порядке API
  // (по слагу) — сетка не «дрожит» между рендерами и фильтрами. `filter` уже
  // вернул новый массив, так что проп `boards` не мутируется.
  const visible = useMemo(
    () =>
      boards
        .filter((b) =>
          filter === "premium" ? b.is_premium : filter === "free" ? !b.is_premium : true,
        )
        .sort((a, b) => (b.media_count || 0) - (a.media_count || 0)),
    [boards, filter],
  );

  const totalFiles = visible.reduce((sum, b) => sum + (b.media_count || 0), 0);

  if (boards.length === 0) {
    return (
      <div className="rounded border border-dashed border-line py-20 text-center">
        <p className="font-mono text-xs uppercase tracking-widest text-text-muted">
          архив пуст
        </p>
        <p className="mt-2 text-sm text-text-secondary">
          Разделы появятся здесь автоматически.
        </p>
      </div>
    );
  }

  return (
    <div>
      {/* Фильтры */}
      <div className="mb-5 flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => setFilter(f.value)}
            className={`filter-btn font-mono text-[11px] ${
              filter === f.value ? "filter-btn-active" : ""
            }`}
          >
            {f.label}
          </button>
        ))}
        <span className="ml-auto flex items-center gap-2">
          <span
            className="font-mono text-[11px] text-text-muted"
            title="Разделы отсортированы по количеству файлов: крупные сверху"
          >
            {formatNumber(visible.length)} разделов · {formatNumber(totalFiles)} файлов
          </span>
          {/* Вид каталога: плитки с обложками или список — список читается как оглавление */}
          <span className="flex items-center gap-1">
            {VIEWS.map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => pickView(item.value)}
                aria-pressed={view === item.value}
                className={`rounded border px-2 py-0.5 font-mono text-[10px] transition-colors ${
                  view === item.value
                    ? "border-accent-primary text-accent-primary"
                    : "border-line text-text-muted hover:text-text-primary"
                }`}
              >
                {item.label}
              </button>
            ))}
          </span>
        </span>
      </div>

      {view === "list" ? (
        /* Список: строка = раздел — читается как оглавление архива,
           не спутать с лентой файлов */
        <div className="flex flex-col gap-2">
          {visible.map((b) => (
            <Link
              key={b.id}
              href={`/board/${b.slug}`}
              className="group flex items-center gap-3 rounded border border-line bg-ink-secondary px-3 py-2 transition-colors hover:border-accent-primary"
            >
              <LayersIcon className="h-4 w-4 shrink-0 text-accent-primary" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-text-primary">
                  {boardTitle(b)}
                </span>
                <span className="block truncate font-mono text-[10px] text-text-muted">
                  раздел/{b.slug}
                </span>
              </span>
              {b.is_premium ? (
                <span
                  className={`badge shrink-0 ${b.locked ? "badge-warn" : "badge-ok"}`}
                  title={
                    b.locked
                      ? "Премиум-раздел: нужна подписка"
                      : "Премиум-раздел: доступен по вашей подписке"
                  }
                >
                  premium
                </span>
              ) : null}
              <span className="shrink-0 font-mono text-[11px] tabular-nums text-text-secondary">
                {formatNumber(b.media_count)}
                {b.media_today ? (
                  <span
                    className="ml-1.5 text-accent-secondary"
                    title={`+${b.media_today} за текущие сутки (после 00:00 МСК)`}
                  >
                    +{formatNumber(b.media_today)}
                  </span>
                ) : null}
              </span>
              <span className="shrink-0 font-mono text-[10px] text-text-muted transition-colors group-hover:text-accent-primary">
                →
              </span>
            </Link>
          ))}
        </div>
      ) : (
        /* Плитки: паспорт раздела + обложка с названием поверх */
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {visible.map((b, idx) => (
          <Link
            key={b.id}
            href={`/board/${b.slug}`}
            className="group flex flex-col overflow-hidden rounded border border-line bg-ink-secondary transition-colors duration-150 hover:border-accent-primary"
          >
            {/* Паспорт раздела: значок, слово «раздел» и адрес — сразу видно,
                что это раздел, а не ещё одна карточка файла */}
            <span className="flex items-center gap-2 border-b border-line bg-ink-tertiary/50 px-3 py-1.5">
              <LayersIcon className="h-3.5 w-3.5 shrink-0 text-accent-primary" aria-hidden />
              <span className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
                раздел
              </span>
              <span className="ml-auto truncate font-mono text-[10px] text-text-muted">
                /{b.slug}
              </span>
              {b.is_premium ? (
                <span
                  className={`badge shrink-0 ${b.locked ? "badge-warn" : "badge-ok"}`}
                  title={
                    b.locked
                      ? "Премиум-раздел: нужна подписка"
                      : "Премиум-раздел: доступен по вашей подписке"
                  }
                >
                  premium
                </span>
              ) : null}
            </span>

            {/* Обложка: мозаика приглушена, название — поверх на градиенте.
                Первые две карточки выше сгиба: их плитки грузим сразу (LCP) */}
            <span className="relative block">
              <CoverMosaic board={b} eager={idx < 2} />
              <span className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink-primary via-ink-primary/80 to-transparent px-3 pb-2 pt-8">
                <span
                  className="block truncate text-base font-semibold leading-snug text-text-primary"
                  title={boardTitle(b)}
                >
                  {boardTitle(b)}
                </span>
              </span>
            </span>

            <div className="flex flex-1 flex-col justify-between gap-2 p-3">
              {/* Подвал плитки: счётчики. Название и адрес — в паспорте и на обложке */}
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10px] text-text-muted">
                  {formatNumber(b.media_count)} файлов
                  {/* Прирост за текущие отчётные сутки (МСК, с 00:00) */}
                  {b.media_today ? (
                    <span
                      className="ml-1.5 text-accent-secondary"
                      title={`+${b.media_today} за текущие сутки (после 00:00 МСК)`}
                    >
                      +{formatNumber(b.media_today)}
                    </span>
                  ) : null}
                </span>
                {/* Доступ виден бейджем в паспорте раздела, здесь — просто переход */}
                <span className="font-mono text-[10px] text-text-muted transition-colors group-hover:text-accent-primary">
                  открыть →
                </span>
              </div>
            </div>
          </Link>
          ))}
        </div>
      )}
    </div>
  );
}
