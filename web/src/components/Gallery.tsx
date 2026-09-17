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
 * Максимальная скорость прокрутки ленты, px/с.
 *
 * Колесо и свайпы не двигают страницу напрямую: они задают цель, а лента едет к ней
 * по кадрам не быстрее этой скорости. Так «разогнать» прокрутку нельзя (ни колесом,
 * ни свайпом), но движение остаётся плавным — без шагов и рывков.
 */
const FEED_MAX_SPEED = 1600;

/**
 * На сколько экранов цель может «убежать» от текущего положения.
 *
 * Ограничивает «накрученную» инерцию: если быстро крутить колесо, цель не уходит
 * бесконечно вперёд, и лента не едет ещё долго после того, как зритель остановился.
 */
const FEED_LOOKAHEAD_SCREENS = 2;

/** Насколько усиливаем одно движение колеса (px дельты → px цели). */
const FEED_WHEEL_GAIN = 1.5;

/**
 * Коэффициент сглаживания (1/с): чем больше, тем быстрее лента догоняет цель.
 * Даёт плавный разгон и мягкую остановку вместо мгновенного старта/стопа.
 */
const FEED_EASE = 9;

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
  // Ограничение скорости автоподгрузки: когда был последний запрос и что запланировано
  const lastLoadRef = useRef(0);
  const stepTimerRef = useRef<number | null>(null);
  // Ограничение прокрутки: цель (куда едем), кадр анимации и состояние жеста
  const scrollRef = useRef<{
    target: number;
    raf: number | null;
    lastFrame: number;
    touch: { x: number; y: number } | null;
  }>({ target: 0, raf: null, lastFrame: 0, touch: null });

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
   * Плавная прокрутка с ограничением скорости.
   *
   * Колесо и свайпы не двигают ленту напрямую: они задают цель, а страница едет к ней
   * по кадрам (rAF) не быстрее `FEED_MAX_SPEED`. Поэтому «разогнать» прокрутку нельзя —
   * ввод можно крутить/свайпать как угодно — но движение остаётся плавным, без шагов
   * и рывков. Цель дополнительно ограничена: не ниже загруженного контента (запас
   * `FEED_TAIL_PX`, чтобы дотянуться до служебных кнопок) и не дальше
   * `FEED_LOOKAHEAD_SCREENS` экранов от фактического положения (чтобы «накрученная»
   * инерция не ехала потом полминуты).
   */
  useEffect(() => {
    if (!infinite) return;
    const state = scrollRef.current;

    /** Докуда пускаем прокрутку: конец загруженного контента + запас. */
    const bottomLimit = () => {
      const max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      const node = sentinelRef.current;
      if (!node || !hasMore) return max;
      const sentinelBottom = node.getBoundingClientRect().bottom + window.scrollY;
      return Math.max(0, Math.min(max, sentinelBottom + FEED_TAIL_PX - window.innerHeight));
    };

    /** Есть ли вообще куда прокручивать (в лайтбоксе страница заперта). */
    const scrollable = () => document.documentElement.scrollHeight - window.innerHeight > 1;

    const cancelFrame = () => {
      if (state.raf !== null) {
        window.cancelAnimationFrame(state.raf);
        state.raf = null;
      }
    };

    /** Один кадр: подтягиваем страницу к цели с ограничением скорости. */
    const frame = () => {
      state.raf = null;
      const now = performance.now();
      const dt = Math.min(0.05, Math.max(0.001, (now - state.lastFrame) / 1000));
      state.lastFrame = now;

      const from = window.scrollY;
      const diff = state.target - from;
      if (Math.abs(diff) < 0.5) {
        state.target = from;
        return;
      }
      // Экспоненциальное сглаживание: у цели движение замедляется (мягкая остановка),
      // а разогнаться выше предела не даёт `maxStep`
      const maxStep = FEED_MAX_SPEED * dt;
      const eased = diff * FEED_EASE * dt;
      const step = Math.max(-maxStep, Math.min(maxStep, Math.abs(eased) < 1 ? diff : eased));
      window.scrollTo(0, from + step);
      state.raf = window.requestAnimationFrame(frame);
    };

    const ensureFrame = () => {
      if (state.raf !== null) return;
      state.lastFrame = performance.now();
      state.raf = window.requestAnimationFrame(frame);
    };

    /** Сдвигает цель (и запускает движение), удерживая её в допустимых границах. */
    const push = (delta: number) => {
      if (!scrollable()) return;
      const from = state.raf === null ? window.scrollY : state.target;
      const max = Math.max(bottomLimit(), window.scrollY);
      const cap = window.innerHeight * FEED_LOOKAHEAD_SCREENS;
      const next = Math.max(0, Math.min(max, from + delta));
      state.target = Math.max(window.scrollY - cap, Math.min(window.scrollY + cap, next));
      ensureFrame();
    };

    const onWheel = (event: WheelEvent) => {
      // Масштабирование (ctrl+колесо) не перехватываем
      if (event.ctrlKey) return;
      // Событие уже обработали выше (карусель превью в плитке, лайтбокс): не мешаем
      if (event.defaultPrevented) return;
      if (!event.deltaY) return;
      if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;

      // Дельту приводим к пикселям: у «строчного» режима единица — строка, у
      // «страничного» — экран (в браузерах это редкость, но пусть будет корректно)
      const unit =
        event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? window.innerHeight : 1;
      push(event.deltaY * unit * FEED_WHEEL_GAIN);
      event.preventDefault();
    };

    const onTouchStart = (event: TouchEvent) => {
      state.touch = event.touches.length === 1
        ? { x: event.touches[0].clientX, y: event.touches[0].clientY }
        : null;
    };

    const onTouchMove = (event: TouchEvent) => {
      const touch = state.touch;
      if (!touch || event.defaultPrevented || event.touches.length !== 1) return;
      const point = event.touches[0];
      const dx = point.clientX - touch.x;
      const dy = point.clientY - touch.y;
      // Горизонтальный жест — не наш: его обрабатывает карусель превью в плитке
      if (Math.abs(dx) > Math.abs(dy)) return;
      if (!scrollable()) return;
      state.touch = { x: point.clientX, y: point.clientY };
      push(-dy); // палец вверх → лента вниз
      event.preventDefault();
    };

    const onTouchEnd = () => {
      state.touch = null;
    };

    // Прокрутку не мы (клавиатура, полоса, программный сдвиг) — берём факт за цель,
    // иначе следующий жест прыгнул бы к «старой» цели
    const onScroll = () => {
      if (state.raf === null) state.target = window.scrollY;
    };

    window.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("touchstart", onTouchStart, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("touchend", onTouchEnd, { passive: true });
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
      window.removeEventListener("scroll", onScroll);
      cancelFrame();
      state.touch = null;
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
          <div className="flex items-start gap-3">
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
