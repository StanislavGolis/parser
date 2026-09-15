"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import Link from "next/link";

import BoardBadge from "@/components/BoardBadge";
import DownloadButton from "@/components/DownloadButton";
import MarkButton from "@/components/MarkButton";
import MediaFilmstrip from "@/components/MediaFilmstrip";
import ReportButton from "@/components/ReportButton";
import {
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CloseIcon,
  DownloadIcon,
  EyeIcon,
  FilmIcon,
  HelpIcon,
  ImageIcon,
  LockIcon,
  SpinnerIcon,
} from "@/components/icons";
import { apiGet } from "@/lib/api";
import { mediaUrl, PREMIUM_CTA_URL } from "@/lib/env";
import { formatBytes, formatCompact, formatDuration } from "@/lib/format";
import { webSrc, premiumState } from "@/lib/media";
import { saveResume } from "@/lib/resume";
import { useMarkToggle } from "@/lib/useMark";
import type { BoardsById, MediaItem, ViewResult } from "@/lib/types";

// Листание колесом (W1): накапливаем дельту до порога и держим «кулдаун»,
// чтобы инерционное колесо/трекпад не проматывал десяток файлов сразу.
const WHEEL_STEP = 40; // px накопленной дельты = один файл
const WHEEL_COOLDOWN_MS = 300; // пауза после перелистывания
const TOAST_MS = 1400; // сколько показываем плашку про метку

// Свайпы (мобильные): пороги в пикселях и максимальная длительность жеста.
const SWIPE_DX = 55; // влево/вправо — листать файлы
const SWIPE_DY = 85; // вниз — закрыть просмотр
const SWIPE_MAX_MS = 800; // медленнее — считаем это скроллом/выделением, не свайпом

/**
 * Соседний файл в слайд-ленте: стоит за кадром — слева или справа от текущего.
 * При протяжке он «подтягивается» в кадр, поэтому перелистывание читается как
 * сдвиг ленты, а не как мгновенная подмена картинки. Видео здесь показываем
 * постером: грузить сам файл в соседнем слайде нельзя — протяжка «залипает».
 */
function NeighbourSlide({ src, side, locked }: { src: string; side: "left" | "right"; locked: boolean }) {
  if (!src) return null;
  return (
    <div
      className="pointer-events-none absolute inset-0 flex items-center justify-center"
      style={{ transform: side === "left" ? "translateX(-100%)" : "translateX(100%)" }}
      aria-hidden
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt=""
        loading="eager"
        decoding="async"
        referrerPolicy="no-referrer"
        className={`max-h-[min(88vh,100%)] w-auto max-w-full rounded object-contain sm:max-h-[min(74vh,100%)] ${
          locked ? "scale-110 blur-[8px]" : ""
        }`}
      />
    </div>
  );
}

/** Сколько соседних файлов прогреваем заранее — чтобы быстрый свайп не «залипал». */
const PRELOAD_RADIUS = 3;

/**
 * Кадр для слайда ленты: у картинок — веб-версия (крупнее и уже сжата), у видео —
 * постер. Сам видеофайл в соседних слайдах не грузим: иначе протяжка «залипает».
 */
function slideSrc(item: MediaItem): string {
  if (item.media_type === "video") return mediaUrl(item.thumb_url ?? item.blur_url) ?? "";
  return mediaUrl(item.web_url) ?? mediaUrl(item.thumb_url) ?? "";
}

interface LightboxProps {
  items: MediaItem[];
  index: number;
  boardsById?: BoardsById;
  onClose: () => void;
  onPrev: () => void;
  onNext: () => void;
  /** Перейти к произвольному файлу (клик по миниатюре карусели). */
  onSelect?: (index: number) => void;
  /**
   * Контекст «треда» для точки возврата: id и **полный** размер треда (файлов).
   * Размер передаём отдельно: в порции из API приходит максимум 300 файлов, и
   * если считать по ней, «+N новых в конце» показывало бы лишнее (например,
   * «+582» в треде из 882 файлов).
   */
  resumeThreadId?: number;
  resumeTotal?: number;
  /** Есть ли ещё не загруженные файлы (тредовые галереи грузятся порциями). */
  hasMore?: boolean;
  loadingMore?: boolean;
  onLoadMore?: () => void;
}

/** Чип клавиши/жеста в строке подсказок. */
function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded border border-line bg-ink-tertiary px-1 py-0.5 font-mono text-[10px] text-text-secondary">
      {children}
    </span>
  );
}

/** Строка подсказки «клавиша — что делает» в оверлее лайтбокса. */
function HintRow({ keys, text }: { keys: string; text: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="inline-flex min-w-16 justify-center rounded border border-line bg-ink-tertiary px-1.5 py-0.5 font-mono text-[11px] text-text-primary">
        {keys}
      </span>
      <span>{text}</span>
    </div>
  );
}

export default function Lightbox({
  items,
  index,
  boardsById,
  onClose,
  onPrev,
  onNext,
  onSelect,
  resumeThreadId,
  resumeTotal,
  hasMore = false,
  loadingMore = false,
  onLoadMore,
}: LightboxProps) {
  const media = items[index];
  const board = media ? boardsById?.[media.board_id] : undefined;
  const [failed, setFailed] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  // Подробная подсказка: по умолчанию скрыта — внизу окна всегда висит строка
  // подсказок, а подробную плашку вызывают кнопкой «?» или клавишей «?».
  const [showHint, setShowHint] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  // Локальные правки метки: при листании «вперёд-назад» данные приходят из
  // исходной выборки, поэтому запоминаем изменения, сделанные в просмотре.
  const [markOverrides, setMarkOverrides] = useState<
    Record<number, { marked: boolean; marksCount: number }>
  >({});

  const override = media ? markOverrides[media.id] : undefined;

  // Метку ведём здесь: её переключают и кнопка в панели, и пробел
  const mark = useMarkToggle(
    media?.id ?? 0,
    override?.marked ?? Boolean(media?.marked),
    override?.marksCount ?? media?.marks_count ?? 0,
  );

  useEffect(() => {
    setFailed(false);
  }, [media?.id, media?.url]);

  // Прогрев соседних кадров: пока зритель смотрит файл, в браузерном кэше уже
  // лежат ±PRELOAD_RADIUS превью — быстрый свайп не показывает «пустые» слайды.
  // Класть в кэш больше не нужно: это лишний трафик на мобильном интернете.
  useEffect(() => {
    if (items.length === 0 || !media) return;
    const urls: string[] = [slideSrc(media)];
    const radius = Math.min(PRELOAD_RADIUS, items.length - 1);
    for (let step = 1; step <= radius; step += 1) {
      const forward = items[(index + step) % items.length];
      const backward = items[(index - step + items.length) % items.length];
      if (forward) urls.push(slideSrc(forward));
      if (backward) urls.push(slideSrc(backward));
    }
    // Не конкурируем с первым рендером: превью догружаем следующим тиком
    const timer = window.setTimeout(() => {
      urls.forEach((url) => {
        if (!url || preloadedRef.current.has(url)) return;
        preloadedRef.current.add(url);
        const img = new window.Image();
        img.decoding = "async";
        img.src = url;
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [items, index, media]);

  // Точка возврата «продолжить просмотр»: запоминаем, какой файл треда открыт
  // сейчас, чтобы в следующий заход открыть тред на нём. Пишем только для
  // тредовой галереи: в смешанной ленте (главная, поиск, метки) позиция ничего
  // не значит — продолжать там нечего.
  //
  // Размер треда берём из контекста (`resumeTotal`), а не из `items.length`:
  // галерея грузится порциями по 300 файлов, и по порции «+N новых в конце»
  // считалось неверно (в треде из 882 файлов показывало «+582»).
  const threadId = useMemo(() => {
    if (resumeThreadId) return resumeThreadId;
    return items.length > 0 && items.every((m) => m.thread_id === items[0].thread_id)
      ? items[0].thread_id
      : 0;
  }, [resumeThreadId, items]);

  useEffect(() => {
    if (!threadId || !media || !resumeTotal) return;
    saveResume(threadId, media.id, index, resumeTotal);
  }, [threadId, media, index, resumeTotal]);

  // ── Свайпы (мобильные) ───────────────────────────────────────────
  // Влево/вправо — листать файлы: за пальцем следует ТОЛЬКО медиа, интерфейс
  // (шапка, панели, счётчик) стоит на месте. Вниз — закрыть просмотр.
  // Жесты, начатые на видео (там своя перемотка) и на элементах со своим
  // скроллом, игнорируем.
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const backdropRef = useRef<HTMLDivElement | null>(null);
  // Соседние слайды подключаем только после начала горизонтального жеста:
  // иначе на каждое открытие файла грузились бы два лишних превью
  const [neighbours, setNeighbours] = useState(false);
  const touchRef = useRef<{
    x: number;
    y: number;
    at: number;
    active: boolean;
    axis: "x" | "y" | null;
  } | null>(null);
  const movedRef = useRef(false);
  // Уже прогретые кадры: повторно не грузим, даже если листать туда-сюда
  const preloadedRef = useRef<Set<string>>(new Set());
  // Листать можно, только если в списке больше одного файла
  const canSlide = items.length > 1;

  /** Смещает слой медиа (интерфейс не двигается). */
  const setSurface = useCallback((value: string, transition = "") => {
    const node = surfaceRef.current;
    if (!node) return;
    node.style.transition = transition;
    node.style.transform = value;
  }, []);

  const resetSwipe = useCallback(() => {
    setSurface("", "transform 180ms cubic-bezier(0.22, 1, 0.36, 1)");
    const back = backdropRef.current;
    if (back) {
      back.style.transition = "opacity 180ms ease-out";
      back.style.opacity = "1";
      window.setTimeout(() => {
        back.style.transition = "";
      }, 220);
    }
    window.setTimeout(() => {
      const node = surfaceRef.current;
      if (node) node.style.transition = "";
    }, 220);
  }, [setSurface]);

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    if (e.touches.length !== 1) {
      touchRef.current = null; // пинч/мультитач — не наш жест
      return;
    }
    const target = e.target as HTMLElement | null;
    const touch = e.touches[0];
    // Плеер листается жестом как обычная картинка (вбок — листание, вниз — закрыть),
    // а перемотка остаётся за полосой прогресса: касание в нижней зоне видео и
    // элементы со своим скроллом (карусель миниатюр) не перехватываем.
    const video = target?.closest("video") as HTMLVideoElement | null;
    let controlsZone = false;
    if (video) {
      const rect = video.getBoundingClientRect();
      // Нижняя полоса контролов (обычно ~48–64 px), но не больше четверти высоты
      const zone = Math.min(72, rect.height * 0.25);
      controlsZone = touch.clientY >= rect.bottom - zone;
    }
    const ignored = controlsZone || Boolean(target?.closest("[data-wheel-ignore]"));
    touchRef.current = {
      x: touch.clientX,
      y: touch.clientY,
      at: Date.now(),
      active: !ignored,
      axis: null,
    };
    movedRef.current = false;
  }, []);

  const onTouchMove = useCallback(
    (e: React.TouchEvent) => {
      const state = touchRef.current;
      if (!state?.active) return;
      const touch = e.touches[0];
      const dx = touch.clientX - state.x;
      const dy = touch.clientY - state.y;
      const distance = Math.abs(dx) + Math.abs(dy);
      if (distance > 10) movedRef.current = true;

      // Ось фиксируем один раз: дальше жест идёт либо по горизонтали (листание),
      // либо по вертикали (закрытие) — медиа не «виляет» по диагонали.
      if (!state.axis) {
        if (distance < 10) return;
        state.axis = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
      }

      if (state.axis === "x") {
        // Ленту собираем только когда человек реально потянул в сторону
        setNeighbours(true);
        setSurface(`translate3d(${dx * 0.75}px, 0, 0)`);
        return;
      }
      // Вверх не тянем: жест закрытия — только вниз
      const down = Math.max(0, dy);
      setSurface(`translate3d(0, ${down * 0.7}px, 0)`);
      const back = backdropRef.current;
      if (back) back.style.opacity = String(Math.max(0.25, 1 - down / 420));
    },
    [setSurface],
  );

  const onTouchEnd = useCallback(
    (e: React.TouchEvent) => {
      const state = touchRef.current;
      touchRef.current = null;
      if (!state?.active) return;

      const touch = e.changedTouches[0];
      const dx = touch.clientX - state.x;
      const dy = touch.clientY - state.y;
      const fast = Date.now() - state.at < SWIPE_MAX_MS;

      if (fast && state.axis === "y" && dy > SWIPE_DY) {
        // Свайп вниз — закрыть: медиа уезжает, затемнение тает, окно закрывается
        setSurface("translate3d(0, 105%, 0)", "transform 170ms ease-out");
        const back = backdropRef.current;
        if (back) {
          back.style.transition = "opacity 170ms ease-out";
          back.style.opacity = "0";
        }
        window.setTimeout(onClose, 150);
        return;
      }

      if (fast && state.axis === "x" && Math.abs(dx) > SWIPE_DX && items.length > 1) {
        // Доводим ленту до соседнего слайда (он уже стоит рядом, см. NeighbourSlide)
        // и подменяем файл так, что он оказывается в центре — стык незаметен
        setNeighbours(true);
        setSurface(`translate3d(${dx < 0 ? -100 : 100}%, 0, 0)`, "transform 150ms ease-out");
        window.setTimeout(() => {
          setSurface("", "");
          if (dx < 0) onNext();
          else onPrev();
        }, 150);
        return;
      }

      resetSwipe();
    },
    [items.length, onClose, onNext, onPrev, resetSwipe, setSurface],
  );

  const onTouchCancel = useCallback(() => {
    touchRef.current = null;
    resetSwipe();
  }, [resetSwipe]);

  useEffect(() => {
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, []);

  useEffect(() => {
    if (!media) return;
    apiGet<ViewResult>(`/api/v1/media/${media.id}/view`).catch(() => {});
  }, [media]);

  const toggleMark = mark.toggle;

  // Плашка про закладку (пробел/кнопка) + запоминаем правку для этого файла
  useEffect(() => {
    if (!mark.lastAction) return;
    if (media) {
      setMarkOverrides((prev) => ({
        ...prev,
        [media.id]: { marked: mark.marked, marksCount: mark.marksCount },
      }));
    }
    setToast(
      mark.lastAction === "marked"
        ? `Закладка добавлена · ${mark.marksCount}`
        : "Закладка снята",
    );
    const timer = window.setTimeout(() => setToast(null), TOAST_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mark.lastAction, mark.marksCount]);

  const onKeyDown = useCallback(
    (e: KeyboardEvent) => {
      // «?» (или h) — переключить подробную подсказку; любая другая клавиша её закрывает
      if (e.key === "?" || e.key === "h" || e.key === "H") {
        setShowHint((visible) => !visible);
        return;
      }
      setShowHint(false);

      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft") onPrev();
      else if (e.key === "ArrowRight") onNext();
      else if (e.code === "Space" || e.key === " ") {
        // Пробел = метка. preventDefault обязателен: иначе браузер «нажмёт»
        // сфокусированную кнопку (например, «Скачать») и проскроллит страницу.
        e.preventDefault();
        void toggleMark();
      }
    },
    [onClose, onPrev, onNext, toggleMark],
  );

  useEffect(() => {
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onKeyDown]);

  // Листание колесом: порог + кулдаун. Ctrl/⌘ не перехватываем (зум браузера),
  // над каруселью миниатюр (data-wheel-ignore) — не листаем (там свой скролл).
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    let acc = 0;
    let cooldown = false;

    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("[data-wheel-ignore]")) return;

      event.preventDefault();
      if (cooldown || items.length < 2) return;

      // Firefox шлёт построчный скролл (deltaMode=1), редко — страничный (2)
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? el.clientHeight : 1;
      acc += (event.deltaY + event.deltaX) * unit;
      if (Math.abs(acc) < WHEEL_STEP) return;

      const direction = acc > 0 ? 1 : -1; // вниз — следующий, вверх — предыдущий
      acc = 0;
      cooldown = true;
      window.setTimeout(() => {
        cooldown = false;
      }, WHEEL_COOLDOWN_MS);
      if (direction > 0) onNext();
      else onPrev();
    };

    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [onNext, onPrev, items.length]);

  if (!media) return null;

  const isVideo = media.media_type === "video";
  const premium = premiumState(media);
  const locked = premium === "locked";
  const canShow = !locked && Boolean(media.url || media.web_url || media.thumb_url) && !failed;
  // Позицию показываем от полного размера треда (если он известен): в порцию
  // входит максимум 300 файлов, а в треде их бывает больше.
  const position = `${index + 1} / ${resumeTotal && resumeTotal > items.length ? resumeTotal : items.length}`;

  // Соседи по ленте (с закольцовыванием): их кадры подтягиваются при протяжке
  const prevItem = canSlide ? items[(index - 1 + items.length) % items.length] : null;
  const nextItem = canSlide ? items[(index + 1) % items.length] : null;

  return (
    <div
      ref={containerRef}
      // Затемнение теперь отдельным слоем: при свайпе вниз оно «тает», а окно
      // остаётся непрозрачным
      className="fixed inset-0 z-50 flex items-center justify-center p-0 sm:p-4 md:p-6"
      onClick={(e) => {
        if (movedRef.current) {
          movedRef.current = false;
          return;
        }
        const el = e.target as HTMLElement;
        if (el === e.currentTarget || el.dataset.backdrop === "1") onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={media.original_name}
    >
      <div ref={backdropRef} data-backdrop="1" className="absolute inset-0 bg-black/80" aria-hidden />
      {/* Окно плеера: не «на весь экран» — с отступами, поэтому и крестик, и файл
          рядом с курсором; клик по затемнению вокруг закрывает просмотр */}
      <div
        className="relative flex h-full max-h-[100dvh] w-full max-w-[1500px] flex-col overflow-hidden bg-[#050708] shadow-2xl sm:max-h-[92vh] sm:rounded-lg sm:border sm:border-line"
      >
      <div className="flex items-start justify-between gap-2 border-b border-line px-3 py-1.5 sm:gap-4 sm:px-6 sm:py-2.5">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-text-secondary">
            {board ? (
              <span className="hidden sm:inline-flex">
                <BoardBadge board={board} />
              </span>
            ) : null}
            <span className="truncate">{media.original_name}</span>
            <span className="hidden text-text-muted sm:inline">{formatBytes(media.file_size)}</span>
            {media.width && media.height ? (
              <span className="hidden text-text-muted sm:inline">
                {media.width}×{media.height}
              </span>
            ) : null}
            {isVideo ? (
              <span className="badge badge-hot hidden sm:inline-flex">
                <FilmIcon className="h-2.5 w-2.5" />
                {`видео${formatDuration(media.duration_seconds) ? ` ${formatDuration(media.duration_seconds)}` : ""}`}
              </span>
            ) : null}
            {premium ? (
              <span
                className={`badge hidden sm:inline-flex ${premium === "locked" ? "badge-warn" : "badge-ok"}`}
                title={
                  premium === "locked"
                    ? "Премиум-контент: нужна подписка"
                    : "Премиум-контент: доступен по вашей подписке"
                }
              >
                premium
              </span>
            ) : null}
          </div>
          {media.source_md5 || media.file_hash ? (
            // Технический хеш оставляем только на широких экранах: на телефоне он
            // занимал пол-шапки и мешал просмотру файла
            <div className="mt-1 hidden break-all font-mono text-[10px] leading-relaxed text-text-muted sm:block">
              {media.source_md5 ? <>MD5: {media.source_md5}</> : null}
              {media.source_md5 && media.file_hash ? <> &nbsp;·&nbsp; </> : null}
              {media.file_hash ? <>SHA-256: {media.file_hash}</> : null}
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => setShowHint((visible) => !visible)}
            className={`hidden rounded p-2 font-mono text-sm text-text-secondary transition-colors hover:bg-ink-tertiary hover:text-text-primary sm:block ${
              showHint ? "ring-1 ring-accent-primary/50" : ""
            }`}
            aria-label="Подсказка по клавишам (?)"
            title="Подсказка: ? (повторный клик — скрыть)"
          >
            ?
          </button>
          <button
            type="button"
            onClick={onClose}
            className={`rounded p-1.5 text-text-secondary transition-colors hover:bg-ink-tertiary hover:text-text-primary sm:p-2 ${
              showHint ? "ring-1 ring-accent-primary/50" : ""
            }`}
            aria-label="Закрыть (Esc)"
            title="Закрыть: Esc или клик по фону"
          >
            <CloseIcon className="h-5 w-5" />
          </button>
        </div>
      </div>

      {/* Медиа: клик по пустому месту вокруг файла закрывает окно; свайпы —
          листание (влево/вправо) и закрытие (вниз) на мобильных */}
      <div
        className="relative flex min-h-0 flex-1 touch-none items-center justify-center p-0 sm:p-4"
        onClick={(e) => {
          // Клик после свайпа закрытием не считаем — жест уже обработан
          if (movedRef.current) {
            movedRef.current = false;
            return;
          }
          if (e.target === e.currentTarget) onClose();
        }}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        onTouchCancel={onTouchCancel}
      >
        {/* Слой медиа: только он «идёт» за пальцем при листании — шапка, панели и
            счётчик остаются на месте */}
        <div
          ref={surfaceRef}
          className="relative flex h-full w-full items-center justify-center will-change-transform"
        >
        {/* Соседние файлы ленты: подтягиваются с боков при протяжке */}
        {neighbours && prevItem ? (
          <NeighbourSlide
            src={slideSrc(prevItem)}
            side="left"
            locked={Boolean(prevItem.locked)}
          />
        ) : null}
        {neighbours && nextItem ? (
          <NeighbourSlide
            src={slideSrc(nextItem)}
            side="right"
            locked={Boolean(nextItem.locked)}
          />
        ) : null}
        {canShow ? (
          isVideo ? (
            <video
              src={webSrc(media)}
              // Постер: пока плеер не начал играть, виден кадр (на мобильных
              // браузер сам кадр не рисует, и окно выглядело чёрным)
              poster={mediaUrl(media.thumb_url ?? media.blur_url) ?? undefined}
              controls
              autoPlay
              playsInline
              // Нативное «Скачать» из меню плеера: скачивание — премиум-функция,
              // поэтому прячем пункт в controls и контекстное меню браузера.
              controlsList="nodownload noremoteplayback"
              disablePictureInPicture
              onContextMenu={(e) => e.preventDefault()}
              onError={() => setFailed(true)}
              className="max-h-[min(88vh,100%)] w-auto max-w-full rounded sm:max-h-[min(74vh,100%)]"
            >
              Ваш браузер не поддерживает HTML5-видео.
            </video>
          ) : (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={webSrc(media)}
              alt={media.original_name}
              referrerPolicy="no-referrer"
              onError={() => setFailed(true)}
              className="max-h-[min(88vh,100%)] w-auto max-w-full rounded object-contain sm:max-h-[min(74vh,100%)]"
            />
          )
        ) : locked ? (
          <div className="flex flex-col items-center gap-3 rounded border border-accent-warning/40 bg-ink-secondary px-8 py-12 text-center">
            <LockIcon className="h-8 w-8 text-accent-warning" />
            <p className="font-mono text-[11px] uppercase tracking-widest text-accent-warning">
              премиум-контент
            </p>
            <p className="max-w-sm text-xs text-text-secondary">
              Файл доступен по премиум-подписке.
            </p>
            <Link href="/feedback?topic=premium" className="btn-primary px-4 py-2 text-xs">
              Запросить доступ
            </Link>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3 rounded border border-line bg-ink-secondary px-8 py-12 text-center">
            {isVideo ? <FilmIcon className="h-8 w-8 text-text-muted" /> : <ImageIcon className="h-8 w-8 text-text-muted" />}
            <p className="font-mono text-[11px] uppercase tracking-widest text-text-muted">
              файл недоступен
            </p>
            <p className="max-w-sm text-xs text-text-secondary">
              Не удалось загрузить объект из хранилища (возможно, временный лимит или файл удалён).
            </p>
          </div>
        )}
        </div>

        {/* Подсказка по клавишам: только подсказка, клики проходят сквозь неё
            (первый же клик работает как обычно и убирает её) */}
        {showHint ? (
          <div className="pointer-events-none absolute inset-x-0 top-1/2 z-10 -translate-y-1/2 px-4">
            <div className="mx-auto max-w-md rounded-lg border border-accent-primary/40 bg-black/85 p-4 backdrop-blur-sm">
              <div className="font-mono text-[10px] uppercase tracking-wider text-accent-primary">
                управление с клавиатуры
              </div>
              <div className="mt-2 flex flex-col gap-1.5 text-xs text-text-secondary">
                <HintRow keys="← →" text="предыдущий / следующий файл" />
                <HintRow keys="колесо" text="листать файлы" />
                <HintRow keys="пробел" text="добавить или снять закладку" />
                <HintRow keys="Esc" text="закрыть — как и клик по фону" />
                <HintRow keys="? →" text="подробная подсказка (кнопка «подсказка» внизу)" />
                <div className="sm:hidden">
                  <HintRow keys="свайп" text="вниз — закрыть, влево/вправо — листать" />
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {/* Карусель файлов треда (быстрая навигация). На телефоне скрыта: место
          отдаём просмотру, листать можно свайпами */}
      {onSelect ? (
        <div className="hidden sm:block">
          <MediaFilmstrip items={items} index={index} onSelect={onSelect} />
        </div>
      ) : null}

      {/* Нижняя панель */}
      <div className="flex flex-col gap-2 border-t border-line px-3 py-1.5 sm:px-6 sm:py-2.5">
        <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-text-secondary">
          <span className="hidden items-center gap-1.5 sm:inline-flex">
            <EyeIcon className="h-3.5 w-3.5" />
            {formatCompact(media.views_count)} просмотров
          </span>
          <span className="hidden items-center gap-1.5 sm:inline-flex">
            <DownloadIcon className="h-3.5 w-3.5" />
            {formatCompact(media.downloads_count)} скачиваний
          </span>
          {/* Закладка — общий хук: пробел делает то же самое. */}
          <span
            className={showHint ? "inline-flex rounded ring-1 ring-accent-primary/50" : "inline-flex"}
          >
            <MarkButton mediaId={media.id} state={mark} />
          </span>

          {/* Жалоба: уходит в очередь модерации, при «детской безопасности» —
              доступ закрывается сразу (файл и тред скрываются автоматически) */}
          <ReportButton mediaId={media.id} />

          {/* Подробная подсказка: по требованию (кнопка под счётчиками или «?») */}
          <button
            type="button"
            onClick={() => setShowHint((visible) => !visible)}
            className={`hidden items-center gap-1.5 rounded px-2 py-1 font-mono text-[11px] transition-colors sm:inline-flex ${
              showHint
                ? "bg-accent-primary/15 text-accent-primary ring-1 ring-accent-primary/50"
                : "text-text-secondary hover:text-text-primary"
            }`}
            aria-label="Подсказка по клавишам"
            title="Подсказка: ? или эта кнопка"
          >
            <HelpIcon className="h-3.5 w-3.5" />
            подсказка
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onPrev}
            disabled={items.length < 2}
            className={`btn-small px-2.5 py-1.5 ${showHint ? "ring-1 ring-accent-primary/50" : ""}`}
            aria-label="Предыдущий (←)"
            title="Предыдущий: ← или колесо вверх"
          >
            <ChevronLeftIcon className="h-4 w-4" />
          </button>
          <span className="min-w-14 text-center font-mono text-[11px] tabular-nums text-text-muted">
            {position}
          </span>
          {hasMore ? (
            <button
              type="button"
              onClick={onLoadMore}
              disabled={loadingMore}
              className="btn-small px-2.5 py-1.5"
              title={`Загружено ${items.length} из ${resumeTotal ?? items.length} — подгрузить следующую порцию`}
              aria-label="Догрузить файлы треда"
            >
              {loadingMore ? <SpinnerIcon className="h-3.5 w-3.5 animate-spin" /> : <ChevronDownIcon className="h-4 w-4" />}
            </button>
          ) : null}
          <button
            type="button"
            onClick={onNext}
            disabled={items.length < 2}
            className={`btn-small px-2.5 py-1.5 ${showHint ? "ring-1 ring-accent-primary/50" : ""}`}
            aria-label="Следующий (→)"
            title="Следующий: → или колесо вниз"
          >
            <ChevronRightIcon className="h-4 w-4" />
          </button>
          {locked ? (
            <a
              href={PREMIUM_CTA_URL}
              target="_blank"
              rel="noreferrer"
              className="btn-primary px-3 py-1.5 text-xs"
              title="Приватный раздел: тарифы и оплата — в боте"
            >
              <LockIcon className="h-4 w-4" />
              Premium
            </a>
          ) : (
            <DownloadButton mediaId={media.id} size="sm" />
          )}
          </div>
        </div>

        {/* Постоянная строка подсказок: на десктопе — клавиши, на мобильных — жесты.
            Подробную плашку вызывают кнопкой «подсказка» или клавишей «?» */}
        <div className="hidden flex-wrap items-center gap-x-3 gap-y-1 border-t border-line/60 pt-2 font-mono text-[10px] text-text-muted sm:flex">
          <span className="hidden items-center gap-1.5 sm:inline-flex">
            <Kbd>←</Kbd>
            <Kbd>→</Kbd>
            файлы
          </span>
          <span className="hidden items-center gap-1.5 sm:inline-flex">
            <Kbd>колесо</Kbd>
            листать
          </span>
          <span className="hidden items-center gap-1.5 sm:inline-flex">
            <Kbd>пробел</Kbd>
            закладка
          </span>
          <span className="hidden items-center gap-1.5 sm:inline-flex">
            <Kbd>Esc</Kbd>
            закрыть
          </span>
          <span className="inline-flex items-center gap-1.5 sm:hidden">
            <Kbd>свайп ←/→</Kbd>
            файлы
          </span>
          <span className="inline-flex items-center gap-1.5 sm:hidden">
            <Kbd>свайп ↓</Kbd>
            закрыть
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Kbd>?</Kbd>
            подробнее
          </span>
        </div>
      </div>

        {/* Плашка-подтверждение (метка): показывается поверх, не перехватывает клики */}
        {toast ? (
          <div className="pointer-events-none absolute bottom-20 left-1/2 -translate-x-1/2 rounded bg-black/85 px-3 py-1.5 font-mono text-[11px] text-accent-primary">
            {toast}
          </div>
        ) : null}
      </div>
    </div>
  );
}
