"use client";

import { useCallback, useEffect, useRef, useState } from "react";

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
import { useMarkToggle } from "@/lib/useMark";
import type { BoardsById, MediaItem, ViewResult } from "@/lib/types";

// Листание колесом (W1): накапливаем дельту до порога и держим «кулдаун»,
// чтобы инерционное колесо/трекпад не проматывал десяток файлов сразу.
const WHEEL_STEP = 40; // px накопленной дельты = один файл
const WHEEL_COOLDOWN_MS = 300; // пауза после перелистывания
const TOAST_MS = 1400; // сколько показываем плашку про метку
const HINT_MS = 10000; // сколько висит подсказка по клавишам (или до первого действия)

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
  // Подсказка по клавишам: показывается при открытии, гаснет сама или по первому
  // действию (клик / клавиша / колесо); кнопка «?» в шапке — показать снова.
  const [showHint, setShowHint] = useState(true);
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

  // Подсказка: автоскрытие по таймеру…
  useEffect(() => {
    if (!showHint) return;
    const timer = window.setTimeout(() => setShowHint(false), HINT_MS);
    return () => window.clearTimeout(timer);
  }, [showHint]);

  // …и скрытие по первому действию: клик/тап или колесо (клавиши — в onKeyDown,
  // чтобы «?» успевал показать подсказку заново).
  useEffect(() => {
    if (!showHint) return;
    const hide = () => setShowHint(false);
    window.addEventListener("pointerdown", hide);
    window.addEventListener("wheel", hide);
    return () => {
      window.removeEventListener("pointerdown", hide);
      window.removeEventListener("wheel", hide);
    };
  }, [showHint]);

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
      // «?» (или h) — снова показать подсказку; любая другая клавиша её убирает
      if (e.key === "?" || e.key === "h" || e.key === "H") {
        setShowHint(true);
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
      <div className="relative flex h-full max-h-[92vh] w-full max-w-[1500px] flex-col overflow-hidden rounded-lg border border-line bg-[#050708] shadow-2xl">
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
            onClick={() => setShowHint(true)}
            className={`rounded p-2 font-mono text-sm text-text-secondary transition-colors hover:bg-ink-tertiary hover:text-text-primary ${
              showHint ? "ring-1 ring-accent-primary/50" : ""
            }`}
            aria-label="Подсказка по клавишам (?)"
            title="Подсказка по клавишам: ?"
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

      {/* Медиа: клик по пустому месту вокруг файла тоже закрывает окно */}
      <div
        className="relative flex min-h-0 flex-1 items-center justify-center p-2 sm:p-4"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
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
              Файл доступен по премиум-подписке. Активируйте премиум в профиле, чтобы смотреть и
              скачивать полные версии.
            </p>
            <Link href="/profile" className="btn-primary px-4 py-2 text-xs">
              Активировать премиум
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
                <HintRow keys="?" text="показать эту подсказку" />
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {/* Карусель файлов треда (быстрая навигация) */}
      {onSelect ? <MediaFilmstrip items={items} index={index} onSelect={onSelect} /> : null}

      {/* Нижняя панель */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-2.5 sm:px-6">
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

          {/* Повторный вызов подсказки: иконка рядом со счётчиками (та же плашка,
              что появляется при открытии) */}
          <button
            type="button"
            onClick={() => setShowHint(true)}
            className={`inline-flex items-center gap-1.5 rounded px-2 py-1 font-mono text-[11px] transition-colors ${
              showHint
                ? "bg-accent-primary/15 text-accent-primary ring-1 ring-accent-primary/50"
                : "text-text-secondary hover:text-text-primary"
            }`}
            aria-label="Подсказка по клавишам"
            title="Подсказка по клавишам: ? или эта кнопка"
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
            <Link href="/profile" className="btn-primary px-3 py-1.5 text-xs">
              <LockIcon className="h-4 w-4" />
              Premium
            </Link>
          ) : (
            <DownloadButton mediaId={media.id} size="sm" />
          )}
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
