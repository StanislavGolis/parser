"use client";

import { useEffect, useState } from "react";

import { SpinnerIcon, BookmarkIcon } from "@/components/icons";
import { formatCompact } from "@/lib/format";
import type { MarkToggleState } from "@/lib/useMark";
import { useMarkToggle } from "@/lib/useMark";

/**
 * Закладка — личный список лучшего (наш аналог лайка).
 *
 * Доступна только аккаунту: анонима отправляем на вход. Состояние можно вести
 * извне (`state`), например в lightbox, где та же закладка переключается пробелом.
 */
export default function MarkButton({
  mediaId,
  marksCount = 0,
  marked = false,
  variant = "panel",
  state,
  onToggled,
}: {
  mediaId: number;
  marksCount?: number;
  marked?: boolean;
  /** overlay — значок поверх превью карточки, panel — кнопка в нижней панели lightbox. */
  variant?: "overlay" | "panel";
  /** Внешнее состояние (общий хук) — тогда кнопка ничего не ведёт сама. */
  state?: MarkToggleState;
  onToggled?: (state: { marked: boolean; marksCount: number }) => void;
}) {
  const own = useMarkToggle(mediaId, marked, marksCount);
  const active = state ?? own;
  const { marked: isMarked, marksCount: count, busy, toggle } = active;

  // Родителю отдаём изменения (когда состояние ведёт кнопка)
  useEffect(() => {
    if (!state && own.lastAction) {
      onToggled?.({ marked: own.marked, marksCount: own.marksCount });
    }
  }, [state, own.lastAction, own.marked, own.marksCount, onToggled]);

  if (variant === "overlay") {
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          void toggle();
        }}
        disabled={busy}
        title={isMarked ? "Снять закладку (в просмотре — пробел)" : "Добавить в закладки (в просмотре — пробел)"}
        aria-pressed={isMarked}
        className={`inline-flex items-center gap-1 rounded-[3px] px-1.5 py-0.5 font-mono text-[10px] backdrop-blur-sm transition-colors ${
          isMarked
            ? "bg-accent-primary/85 text-ink-primary"
            : "bg-black/60 text-text-secondary hover:text-text-primary"
        }`}
      >
        <BookmarkIcon className="h-3 w-3" />
        {formatCompact(count)}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={() => void toggle()}
      disabled={busy}
      title={
        isMarked
          ? "Снять закладку — пробел"
          : "Добавить в закладки — пробел"
      }
      aria-pressed={isMarked}
      className={`inline-flex items-center gap-1.5 rounded px-2.5 py-1.5 font-mono text-[11px] transition-colors ${
        isMarked
          ? "bg-accent-primary/15 text-accent-primary"
          : "text-text-secondary hover:text-text-primary"
      }`}
    >
      {busy ? <SpinnerIcon className="h-3.5 w-3.5" /> : <BookmarkIcon className="h-3.5 w-3.5" />}
      {isMarked ? "в закладках" : "закладка"}
      <span className="tabular-nums text-text-muted">{formatCompact(count)}</span>
    </button>
  );
}

