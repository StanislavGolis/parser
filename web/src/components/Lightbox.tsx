"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import Link from "next/link";

import BoardBadge from "@/components/BoardBadge";
import DownloadButton from "@/components/DownloadButton";
import MarkButton from "@/components/MarkButton";
import MediaFilmstrip from "@/components/MediaFilmstrip";
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  CloseIcon,
  DownloadIcon,
  EyeIcon,
  FilmIcon,
  HelpIcon,
  ImageIcon,
  LockIcon,
  StarIcon,
} from "@/components/icons";
import { apiGet } from "@/lib/api";
import { mediaUrl } from "@/lib/env";
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

interface LightboxProps {
  items: MediaItem[];
  index: number;
  boardsById?: BoardsById;
  onClose: () => void;
  onPrev: () => void;
  onNext: () => void;
  /** Перейти к произвольному файлу (клик по миниатюре карусели). */
  onSelect?: (index: number) => void;
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

export default function Lightbox({ items, index, boardsById, onClose, onPrev, onNext, onSelect }: LightboxProps) {
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

  // Точка возврата «продолжить просмотр»: запоминаем, какой файл треда открыт
  // сейчас, чтобы в следующий заход открыть тред на нём. Пишем только для
  // тредовой галереи: в смешанной ленте (главная, поиск, метки) позиция ничего
  // не значит — продолжать там нечего.
  const resumeThreadId = useMemo(
    () =>
      items.length > 0 && items.every((m) => m.thread_id === items[0].thread_id)
        ? items[0].thread_id
        : 0,
    [items],
  );

  useEffect(() => {
    if (!resumeThreadId || !media) return;
    saveResume(resumeThreadId, media.id, index, items.length);
  }, [resumeThreadId, media, index, items.length]);

  // ── Свайпы (мобильные) ───────────────────────────────────────────
  // Влево/вправо — листать файлы, вниз — закрыть. Жесты, начатые на видео
  // (там своя перемотка) и на карусели миниатюр (свой скролл), игнорируем.
  const cardRef = useRef<HTMLDivElement | null>(null);
  const touchRef = useRef<{ x: number; y: number; at: number; active: boolean } | null>(null);
  const movedRef = useRef(false);

  const resetCard = useCallback(() => {
    const card = cardRef.current;
    if (!card) return;
    card.style.transition = "transform 160ms ease-out, opacity 160ms ease-out";
    card.style.transform = "";
    card.style.opacity = "";
    window.setTimeout(() => {
      if (card) card.style.transition = "";
    }, 200);
  }, []);

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    if (e.touches.length !== 1) {
      touchRef.current = null; // пинч/мультитач — не наш жест
      return;
    }
    const target = e.target as HTMLElement | null;
    const ignored = Boolean(target?.closest("video") || target?.closest("[data-wheel-ignore]"));
    const touch = e.touches[0];
    touchRef.current = { x: touch.clientX, y: touch.clientY, at: Date.now(), active: !ignored };
    movedRef.current = false;
  }, []);

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    const state = touchRef.current;
    if (!state?.active) return;
    const touch = e.touches[0];
    const dx = touch.clientX - state.x;
    const dy = touch.clientY - state.y;
    if (Math.abs(dx) + Math.abs(dy) > 12) movedRef.current = true;

    // Окно «идёт» за пальцем: правим стиль напрямую, без ререндеров
    const card = cardRef.current;
    if (!card) return;
    card.style.transition = "";
    card.style.transform = `translate(${Math.max(-140, Math.min(140, dx * 0.5))}px, ${Math.max(
      -30,
      Math.min(220, dy * 0.5),
    )}px)`;
    card.style.opacity = dy > 0 ? String(Math.max(0.4, 1 - dy / 500)) : "1";
  }, []);

  const onTouchEnd = useCallback(
    (e: React.TouchEvent) => {
      const state = touchRef.current;
      touchRef.current = null;
      if (!state?.active) return;

      const touch = e.changedTouches[0];
      const dx = touch.clientX - state.x;
      const dy = touch.clientY - state.y;
      const fast = Date.now() - state.at < SWIPE_MAX_MS;
      const horizontal = Math.abs(dx) > Math.abs(dy) * 1.4;
      const vertical = Math.abs(dy) > Math.abs(dx) * 1.4;

      if (fast && vertical && dy > SWIPE_DY) {
        // Свайп вниз — закрыть: окно уезжает, затем закрываем просмотр
        const card = cardRef.current;
        if (card) {
          card.style.transition = "transform 160ms ease-out, opacity 160ms ease-out";
          card.style.transform = "translateY(55%)";
          card.style.opacity = "0";
        }
        window.setTimeout(onClose, 140);
        return;
      }
      if (fast && horizontal && Math.abs(dx) > SWIPE_DX && items.length > 1) {
        // Влево — следующий, вправо — предыдущий
        if (dx < 0) onNext();
        else onPrev();
      }
      resetCard();
    },
    [items.length, onClose, onNext, onPrev, resetCard],
  );

  const onTouchCancel = useCallback(() => {
    touchRef.current = null;
    resetCard();
  }, [resetCard]);

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

  // Плашка про метку (пробел/кнопка) + запоминаем правку для этого файла
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
        ? `Метка поставлена · ${mark.marksCount}`
        : "Метка снята",
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
  const position = `${index + 1} / ${items.length}`;

  return (
    <div
      ref={containerRef}
      // Затемнение вокруг окна: клик по нему закрывает просмотр (как Esc).
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-2 sm:p-4 md:p-6"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={media.original_name}
    >
      {/* Окно плеера: не «на весь экран» — с отступами, поэтому и крестик, и файл
          рядом с курсором; клик по затемнению вокруг закрывает просмотр */}
      <div
        ref={cardRef}
        className="relative flex h-full max-h-[92vh] w-full max-w-[1500px] flex-col overflow-hidden rounded-lg border border-line bg-[#050708] shadow-2xl"
      >
      <div className="flex items-start justify-between gap-4 border-b border-line px-4 py-2.5 sm:px-6">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-text-secondary">
            {board ? <BoardBadge board={board} /> : null}
            <span className="truncate">{media.original_name}</span>
            <span className="text-text-muted">{formatBytes(media.file_size)}</span>
            {media.width && media.height ? (
              <span className="text-text-muted">
                {media.width}×{media.height}
              </span>
            ) : null}
            {isVideo ? (
              <span className="badge badge-hot">
                <FilmIcon className="h-2.5 w-2.5" />
                {`видео${formatDuration(media.duration_seconds) ? ` ${formatDuration(media.duration_seconds)}` : ""}`}
              </span>
            ) : null}
            {premium === "locked" ? (
              <span className="badge badge-warn" title="Премиум-контент: нужна подписка">
                <LockIcon className="h-2.5 w-2.5" />
                premium
              </span>
            ) : premium === "granted" ? (
              <span
                className="badge badge-warn"
                title="Премиум-контент: доступен по вашей подписке"
              >
                <StarIcon className="h-2.5 w-2.5" />
                premium
              </span>
            ) : null}
          </div>
          {media.source_md5 || media.file_hash ? (
            <div className="mt-1 break-all font-mono text-[10px] leading-relaxed text-text-muted">
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
            className={`rounded p-2 font-mono text-sm text-text-secondary transition-colors hover:bg-ink-tertiary hover:text-text-primary ${
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
            className={`rounded p-2 text-text-secondary transition-colors hover:bg-ink-tertiary hover:text-text-primary ${
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
        className="relative flex min-h-0 flex-1 touch-none items-center justify-center p-2 sm:p-4"
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
        {canShow ? (
          isVideo ? (
            <video
              src={webSrc(media)}
              controls
              autoPlay
              playsInline
              onError={() => setFailed(true)}
              className="max-h-[min(74vh,100%)] w-auto max-w-full rounded"
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
              className="max-h-[min(74vh,100%)] w-auto max-w-full rounded object-contain"
            />
          )
        ) : locked ? (
          <div className="flex flex-col items-center gap-3 rounded border border-accent-warning/40 bg-ink-secondary px-8 py-12 text-center">
            <LockIcon className="h-8 w-8 text-accent-warning" />
            <p className="font-mono text-[11px] uppercase tracking-widest text-accent-warning">
              премиум-контент
            </p>
            <p className="max-w-sm text-xs text-text-secondary">
              Файл доступен по премиум-подписке. Запросите доступ — его включают вручную, чтобы смотреть и
              скачивать полные версии.
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
                <HintRow keys="пробел" text="поставить или снять метку" />
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

      {/* Карусель файлов треда (быстрая навигация) */}
      {onSelect ? <MediaFilmstrip items={items} index={index} onSelect={onSelect} /> : null}

      {/* Нижняя панель */}
      <div className="flex flex-col gap-2 border-t border-line px-4 py-2.5 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-text-secondary">
          <span className="inline-flex items-center gap-1.5">
            <EyeIcon className="h-3.5 w-3.5" />
            {formatCompact(media.views_count)} просмотров
          </span>
          <span className="inline-flex items-center gap-1.5">
            <DownloadIcon className="h-3.5 w-3.5" />
            {formatCompact(media.downloads_count)} скачиваний
          </span>
          {/* Метка («отличный контент») — общий хук: пробел делает то же самое. */}
          <span
            className={showHint ? "inline-flex rounded ring-1 ring-accent-primary/50" : "inline-flex"}
          >
            <MarkButton mediaId={media.id} state={mark} />
          </span>

          {/* Подробная подсказка: по требованию (кнопка под счётчиками или «?») */}
          <button
            type="button"
            onClick={() => setShowHint((visible) => !visible)}
            className={`inline-flex items-center gap-1.5 rounded px-2 py-1 font-mono text-[11px] transition-colors ${
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
            <Link href="/feedback?topic=premium" className="btn-primary px-3 py-1.5 text-xs">
              <LockIcon className="h-4 w-4" />
              Premium
            </Link>
          ) : (
            <DownloadButton mediaId={media.id} size="sm" />
          )}
          </div>
        </div>

        {/* Постоянная строка подсказок: на десктопе — клавиши, на мобильных — жесты.
            Подробную плашку вызывают кнопкой «подсказка» или клавишей «?» */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line/60 pt-2 font-mono text-[10px] text-text-muted">
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
            метка
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
