"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import EmptyState from "@/components/EmptyState";
import Lightbox from "@/components/Lightbox";
import MediaCard from "@/components/MediaCard";
import { SpinnerIcon } from "@/components/icons";
import { ApiError, apiGet } from "@/lib/api";
import { trackEvent } from "@/lib/track";
import type { BoardsById, MediaItem, MediaList } from "@/lib/types";

interface GalleryProps {
  /** Первая страница, полученная на сервере (SSR). */
  initial: MediaList;
  /** Путь API без query, например /api/v1/feed. */
  apiPath: string;
  /** Стабильные query-параметры списка (кроме page/per_page). */
  params?: Record<string, string>;
  perPage: number;
  boardsById?: BoardsById;
  /** Показывать бейдж [ТОП] на карточках. */
  showTop?: boolean;
  /**
   * Автодогрузка страниц при скролле. `false` — «витрина»: показываем ровно
   * полученную с сервера страницу и ссылку на полный список (главная страница).
   */
  infinite?: boolean;
  /** Куда ведёт ссылка «показать больше» в режиме витрины. */
  moreHref?: string;
  moreLabel?: string;
  emptyTitle?: string;
  emptyHint?: string;
}

/** Сколько первых карточек грузить сразу (первый экран → LCP). */
const EAGER_CARDS = 6;

/**
 * Пауза между автоподгрузками ленты при быстром скролле (мс).
 *
 * Как в карусели превью треда (`PREVIEW_SCROLL_MS` в `BoardThreads`): шаг даём с
 * паузой, чтобы карточки успели подгрузить превью и лента не уезжала в пустые
 * квадраты. Без паузы быстрый скролл заказывал страницы одну за другой: сервер
 * получал пачку запросов, а картинки всё равно не успевали — зритель видел
 * «мигание» вместо ленты.
 */
const FEED_STEP_MS = 400;

/**
 * Пауза между шагами прокрутки ленты колесом (мс) — та же идея, что
 * `PREVIEW_SCROLL_MS` в карусели превью: одно движение колеса = один шаг, не чаще
 * этой паузы. Иначе лента пролистывается «сквозь» незагруженный контент.
 */
const FEED_WHEEL_MS = 300;

/** Отступ между карточками в колонке (класс `gap-3` у колонки, если мерить нечем). */
const FEED_GAP_PX = 12;

/**
 * Насколько ниже загруженного контента разрешаем прокрутить (px).
 *
 * Это «запас видимости»: в хвосте ленты находятся служебные элементы (кнопка
 * «повторить», плашка «конец списка»), к ним нужно дотянуться мышью.
 */
const FEED_TAIL_PX = 240;

/** Число колонок по ширине окна — как было в CSS (2 / 3 / 4 / 5). */
function useColumnCount(): number {
  const [cols, setCols] = useState(2);

  useEffect(() => {
    const compute = () => {
      const width = window.innerWidth;
      setCols(width >= 1280 ? 5 : width >= 1024 ? 4 : width >= 640 ? 3 : 2);
    };
    compute();
    window.addEventListener("resize", compute);
    return () => window.removeEventListener("resize", compute);
  }, []);

  return cols;
}

/**
 * Оценка высоты карточки в «попугаях» (для балансировки колонок).
 * Пропорции известны из API (`width`/`height`) — раскладываем по самой короткой
 * колонке, как это делал CSS, но без пересборки всей сетки.
 */
function estimateHeight(media: MediaItem): number {
  const w = media.width ?? 0;
  const h = media.height ?? 0;
  const ratio = w > 0 && h > 0 ? h / w : 1.2;
  return Math.min(Math.max(ratio, 0.6), 2.2) + 0.3; // + подпись под карточкой
}

interface Layout {
  /** id карточек по колонкам (слева направо). */
  columns: number[][];
  /** Накопленная высота каждой колонки — для балансировки. */
  heights: number[];
}

function emptyLayout(cols: number): Layout {
  return { columns: Array.from({ length: cols }, () => []), heights: new Array(cols).fill(0) };
}

/**
 * Докладывает новые карточки в колонки, **не трогая уже размещённые**.
 *
 * Именно из-за этого CSS `columns` не годился: при добавлении новых элементов
 * браузер пересобирал всю сетку, и правая часть ленты «заменялась» новыми
 * карточками (казалось, что часть контента потеряна).
 */
function withNewItems(prev: Layout, items: MediaItem[], cols: number): Layout {
  const base = prev.columns.length === cols ? prev : emptyLayout(cols);
  const placed = new Set(base.columns.flat());
  const columns = base.columns.map((column) => column.slice());
  const heights = base.heights.slice();

  for (const item of items) {
    if (placed.has(item.id)) continue;
    let target = 0;
    for (let i = 1; i < heights.length; i += 1) {
      if (heights[i] < heights[target]) target = i;
    }
    columns[target].push(item.id);
    heights[target] += estimateHeight(item);
  }
  return { columns, heights };
}

/**
 * Masonry-галерея с клиентской догрузкой страниц (infinite scroll).
 * Требует "use client", т.к. догрузка идёт fetch из браузера.
 */
export default function Gallery({
  initial,
  apiPath,
  params = {},
  perPage,
  boardsById,
  showTop = false,
  infinite = true,
  moreHref,
  moreLabel,
  emptyTitle,
  emptyHint,
}: GalleryProps) {
  const [items, setItems] = useState<MediaItem[]>(initial.items);
  const [total, setTotal] = useState(initial.total);
  const [page, setPage] = useState(initial.page);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoPaused, setAutoPaused] = useState(false);
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  // Курсорная догрузка: позиция последней карточки. Лента «живая» — новые файлы
  // приходят сверху, поэтому при offset-пагинации страницы сдвигались бы и часть
  // карточек терялась. С курсором догружаем строго то, что ниже последней карточки.
  const [cursor, setCursor] = useState<string | null>(initial.next_cursor ?? null);
  const [cursorMode, setCursorMode] = useState<boolean>(Boolean(initial.next_cursor));
  const cols = useColumnCount();
  const [layout, setLayout] = useState<Layout>(() => withNewItems(emptyLayout(2), initial.items, 2));

  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);
  /** Контейнер колонок — у него меряем высоту одной карточки (шаг прокрутки). */
  const gridRef = useRef<HTMLDivElement | null>(null);
  // Ограничение скорости автоподгрузки: когда был последний запрос и что запланировано
  const lastLoadRef = useRef(0);
  const stepTimerRef = useRef<number | null>(null);
  // Ограничение прокрутки колесом (шаг + пауза, как в карусели превью)
  const wheelRef = useRef<{ last: number; queued: number; timer: number | null }>({
    last: 0,
    queued: 0,
    timer: null,
  });

  const hasMore = cursorMode ? cursor !== null : items.length < total;

  // Раскладка колонок: новые карточки добавляются вниз, уже показанные не двигаются
  useEffect(() => {
    setLayout((prev) => withNewItems(prev, items, cols));
  }, [items, cols]);

  const itemsById = useMemo(() => new Map(items.map((m) => [m.id, m])), [items]);
  const indexById = useMemo(
    () => new Map(items.map((m, idx) => [m.id, idx])),
    [items],
  );
  const queryKey = useMemo(() => Object.entries(params).map(([k, v]) => `${k}=${v}`).join("&"), [params]);

  const loadMore = useCallback(async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    setLoading(true);
    setError(null);

    // Курсорный режим: позицию задаёт курсор (page не участвует)
    const q = new URLSearchParams({ page: "1", per_page: String(perPage) });
    if (cursorMode && cursor) {
      q.set("cursor", cursor);
    } else if (!cursorMode) {
      q.set("page", String(page + 1));
    }
    Object.entries(params).forEach(([k, v]) => {
      if (v) q.set(k, v);
    });

    try {
      const data = await apiGet<MediaList>(`${apiPath}?${q.toString()}`);
      setItems((prev) => {
        const seen = new Set(prev.map((m) => m.id));
        const fresh = data.items.filter((m) => !seen.has(m.id));
        // Новые карточки добавляем строго в конец: список не «прыгает»
        return fresh.length > 0 ? [...prev, ...fresh] : prev;
      });
      setPage(data.page);
      setTotal(data.total);
      if (data.next_cursor) setCursorMode(true);
      setCursor(data.next_cursor ?? null);
      setAutoPaused(false);
    } catch (err) {
      setError(err instanceof ApiError && err.status ? `Не удалось загрузить (HTTP ${err.status})` : "Нет соединения с сервером");
      setAutoPaused(true);
    } finally {
      busyRef.current = false;
      // Пауза считается от **окончания** загрузки: показываем пришедшие карточки,
      // даём браузеру начать грузить их превью — и только потом берём следующую
      // страницу, даже если зритель продолжает быстро скроллить
      lastLoadRef.current = Date.now();
      setLoading(false);
    }
  }, [apiPath, page, perPage, params, cursor, cursorMode]);

  const retry = useCallback(() => {
    setAutoPaused(false);
    setError(null);
    void loadMore();
  }, [loadMore]);

  /**
   * Подгрузка с паузой (шаг ленты).
   *
   * Observer срабатывает на каждое движение у границы, поэтому «просто вызвать
   * loadMore» — значит заказать несколько страниц подряд, пока зритель быстро
   * скроллит. Здесь: если с прошлого запроса прошло меньше `FEED_STEP_MS`,
   * подгрузка откладывается на остаток паузы (и не дублируется).
   */
  const scheduleLoadMore = useCallback(() => {
    const since = Date.now() - lastLoadRef.current;
    if (since >= FEED_STEP_MS) {
      void loadMore();
      return;
    }
    if (stepTimerRef.current !== null) return; // пауза уже запланирована
    stepTimerRef.current = window.setTimeout(() => {
      stepTimerRef.current = null;
      void loadMore();
    }, FEED_STEP_MS - since);
  }, [loadMore]);

  // Таймер шага не должен пережить компонент (иначе запрос уйдёт «в никуда»)
  useEffect(
    () => () => {
      if (stepTimerRef.current !== null) {
        window.clearTimeout(stepTimerRef.current);
        stepTimerRef.current = null;
      }
    },
    [],
  );

  // Infinite scroll: догружаем, когда sentinel появляется в зоне видимости.
  // В режиме витрины (infinite=false) автодогрузки нет — пользователь уходит
  // в полный список по ссылке.
  useEffect(() => {
    if (!infinite) return;
    const node = sentinelRef.current;
    if (!node || !hasMore || loading || autoPaused || error) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) scheduleLoadMore();
      },
      { rootMargin: "900px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [scheduleLoadMore, hasMore, loading, autoPaused, error, queryKey, items.length]);

  /**
   * Прокрутка ленты «шагами», как в карусели превью.
   *
   * Колесо не пролистывает страницу свободно: одно движение = один шаг на высоту
   * одного ряда ленты (карточка + отступ), и не чаще `FEED_WHEEL_MS`. Плюс упор в
   * границу загруженного: ниже последней пришедшей порции прокрутка не уходит
   * (кроме запаса `FEED_TAIL_PX`, чтобы дотянуться до служебных кнопок). Поэтому
   * «улететь» в пустую ленту нельзя — страница ждёт подгрузку, а когда карточки
   * пришли, граница сдвигается вниз.
   *
   * Тач-устройства и клавиатуру не трогаем: там прокрутка нативная.
   */
  useEffect(() => {
    if (!infinite) return;

    /** Докуда пускаем прокрутку: конец загруженного контента + запас. */
    const bottomLimit = () => {
      const max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      const node = sentinelRef.current;
      if (!node || !hasMore) return max;
      const sentinelBottom = node.getBoundingClientRect().bottom + window.scrollY;
      return Math.max(0, Math.min(max, sentinelBottom + FEED_TAIL_PX - window.innerHeight));
    };

    /**
     * Шаг прокрутки = один ряд ленты: высота карточки плюс отступ до следующей.
     *
     * Берём медиану высот нескольких первых карточек первой колонки: одна случайная
     * карточка может оказаться высоким портретом, и шаг «уехал» бы на полтора ряда.
     * Отступ считаем по разнице между первой и второй карточкой. Пока карточек нет
     * (первая загрузка, пустой список) шагаем половиной экрана — прокручивать всё
     * равно нечего.
     */
    const stepOf = () => {
      const column = gridRef.current?.firstElementChild as HTMLElement | null;
      const cards = column ? (Array.from(column.children) as HTMLElement[]).slice(0, 5) : [];
      if (cards.length === 0) return Math.round(window.innerHeight * 0.5);

      const heights = cards
        .map((card) => card.getBoundingClientRect().height)
        .filter((h) => h > 1)
        .sort((a, b) => a - b);
      if (heights.length === 0) return Math.round(window.innerHeight * 0.5);

      const gap =
        cards.length > 1
          ? Math.max(
              0,
              cards[1].getBoundingClientRect().top - cards[0].getBoundingClientRect().bottom,
            )
          : FEED_GAP_PX;
      const median = heights[Math.floor(heights.length / 2)];
      return Math.max(1, Math.round(median + gap));
    };

    const onWheel = (event: WheelEvent) => {
      // Масштабирование (ctrl+колесо) не перехватываем
      if (event.ctrlKey) return;
      // Событие уже обработали выше (карусель превью в плитке, лайтбокс): не мешаем —
      // прокрутка страницы «уходит» ленте только там, где карусель отдала событие
      if (event.defaultPrevented) return;
      if (!event.deltaY) return;
      if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;

      const step = stepOf();
      const direction = event.deltaY > 0 ? 1 : -1;
      const state = wheelRef.current;

      /** Куда попадём шагом с учётом границы загруженного (и края страницы). */
      const targetOf = (dir: number) => {
        const from = window.scrollY;
        if (dir > 0) {
          // Ниже границы не пускаем; если уже ниже — разрешаем только возврат наверх
          const limit = Math.max(bottomLimit(), from);
          return Math.min(from + step, limit);
        }
        return Math.max(from - step, 0);
      };

      // Двигать нечего — отдаём событие странице (например, карусели под курсором)
      if (Math.abs(targetOf(direction) - window.scrollY) < 1) return;
      event.preventDefault();

      const apply = (dir: number) => {
        const to = targetOf(dir);
        if (Math.abs(to - window.scrollY) < 1) return;
        window.scrollTo({ top: to, behavior: "smooth" });
      };

      const wait = FEED_WHEEL_MS - (Date.now() - state.last);
      if (wait <= 0) {
        state.last = Date.now();
        apply(direction);
        return;
      }
      // Крутят быстрее, чем лента успевает: держим один шаг в запасе, остальное теряем
      state.queued = direction;
      if (state.timer === null) {
        state.timer = window.setTimeout(() => {
          state.timer = null;
          state.last = Date.now();
          apply(state.queued);
        }, wait);
      }
    };

    window.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      window.removeEventListener("wheel", onWheel);
      const state = wheelRef.current;
      if (state.timer !== null) {
        window.clearTimeout(state.timer);
        state.timer = null;
      }
    };
  }, [infinite, hasMore]);

  const step = useCallback(
    (dir: 1 | -1) => {
      setOpenIndex((cur) => {
        if (cur === null || items.length < 2) return cur;
        return (cur + dir + items.length) % items.length;
      });
    },
    [items.length],
  );

  const showEmpty = items.length === 0 && !loading && !error;

  return (
    <div>
      {showEmpty ? (
        <EmptyState title={emptyTitle} hint={emptyHint} />
      ) : (
        <>
          <div ref={gridRef} className="flex items-start gap-3">
            {layout.columns.map((column, columnIndex) => (
              <div key={columnIndex} className="flex min-w-0 flex-1 flex-col gap-3">
                {column.map((mediaId) => {
                  const media = itemsById.get(mediaId);
                  if (!media) return null;
                  const idx = indexById.get(mediaId) ?? 0;
                  return (
                    <MediaCard
                      key={media.id}
                      media={media}
                      board={boardsById ? boardsById[media.board_id] : undefined}
                      showTop={showTop}
                      eager={columnIndex < 2 && idx < EAGER_CARDS}
                      onOpen={() => {
                        trackEvent("lightbox_open");
                        setOpenIndex(idx);
                      }}
                    />
                  );
                })}
              </div>
            ))}
          </div>

          {items.length > 0 && items.length < total ? (
            <div className="mt-4 text-center font-mono text-[11px] text-text-muted">
              показано {items.length} из {total}
            </div>
          ) : null}
        </>
      )}

      {error ? (
        <div className="mt-6 flex flex-col items-center gap-3">
          <p className="text-sm text-text-secondary">{error}</p>
          <button type="button" onClick={retry} className="btn-small">
            Повторить загрузку
          </button>
        </div>
      ) : null}

      {/* Sentinel для infinite scroll (только в режиме полного списка) */}
      {infinite && hasMore && !error ? (
        <div ref={sentinelRef} className="flex min-h-16 items-center justify-center py-6">
          {loading ? (
            <span className="inline-flex items-center gap-2 font-mono text-[11px] text-text-secondary">
              <SpinnerIcon className="h-4 w-4 animate-spin" />
              загрузка ещё…
            </span>
          ) : (
            <span className="font-mono text-[11px] text-text-muted">••• прокрутите ниже</span>
          )}
        </div>
      ) : null}

      {/* Режим витрины: без автодогрузки, но с явной ссылкой в полный список */}
      {!infinite && moreHref && items.length > 0 ? (
        <div className="mt-6 text-center">
          <Link href={moreHref} className="btn-ghost">
            {moreLabel ?? "Показать больше"}
          </Link>
        </div>
      ) : null}

      {openIndex !== null ? (
        <Lightbox
          items={items}
          index={openIndex}
          boardsById={boardsById}
          onClose={() => setOpenIndex(null)}
          onPrev={() => step(-1)}
          onNext={() => step(1)}
          onSelect={(i) => setOpenIndex(i)}
        />
      ) : null}
    </div>
  );
}
