"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { mediaUrl } from "@/lib/env";
import { formatNumber } from "@/lib/format";
import type { Board } from "@/lib/types";
import { useImgLoaded } from "@/lib/useImgLoaded";

type Filter = "all" | "free" | "premium";

const FILTERS: Array<{ value: Filter; label: string }> = [
  { value: "all", label: "ВСЕ" },
  { value: "free", label: "БЕЗ ПОДПИСКИ" },
  { value: "premium", label: "ПРЕМИУМ" },
];

/** Сколько превью в мозаике обложки (2×2). */
const MOSAIC_TILES = 4;

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
    <span
      // grid-rows-2 с minmax(0,1fr): строки делят высоту контейнера поровну и
      // не могут вырасти от содержимого — мозаика одинаковая у всех карточек.
      className="grid w-full shrink-0 grid-cols-2 grid-rows-2 gap-px overflow-hidden border-b border-line bg-line"
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
        <span
          className="ml-auto font-mono text-[11px] text-text-muted"
          title="Разделы отсортированы по количеству файлов: крупные сверху"
        >
          {formatNumber(visible.length)} показано · сортировка: файлов ↓
        </span>
      </div>

      {/* Сетка разделов: карточка с мозаикой свежих превью */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {visible.map((b, idx) => (
          <Link
            key={b.id}
            href={`/board/${b.slug}`}
            className="group flex flex-col overflow-hidden rounded border border-line bg-ink-secondary transition-colors duration-150 hover:border-accent-primary"
          >
            {/* Первые две карточки выше сгиба: их плитки грузим сразу (LCP) */}
            <CoverMosaic board={b} eager={idx < 2} />

            <div className="flex flex-1 flex-col justify-between gap-2 p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <span className="font-mono text-sm font-bold uppercase tracking-wider text-text-primary">
                    <span className="mr-1 text-[10px] font-normal tracking-normal text-text-muted">
                      раздел
                    </span>
                    /{b.slug}
                  </span>
                  <p className="mt-0.5 truncate text-xs text-text-secondary" title={b.title || b.slug}>
                    {b.title || b.slug}
                  </p>
                </div>
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
              </div>

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
                {b.is_premium ? (
                  <span className="font-mono text-[10px] text-accent-warning">по подписке</span>
                ) : (
                  <span className="font-mono text-[10px] text-text-muted transition-colors group-hover:text-accent-primary">
                    открыть →
                  </span>
                )}
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
