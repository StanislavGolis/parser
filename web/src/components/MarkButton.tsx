"use client";

import { useEffect, useState } from "react";

import { SpinnerIcon, TagIcon } from "@/components/icons";
import { ApiError, apiPost } from "@/lib/api";
import { formatCompact } from "@/lib/format";
import type { MarkResult } from "@/lib/types";

/**
 * Метка «отличный контент» — наш аналог лайка.
 *
 * Доступна только аккаунту: анонима отправляем на вход. Метка — переключатель,
 * счётчик приходит с сервера (денормализованный `marks_count`).
 */
export default function MarkButton({
  mediaId,
  marksCount = 0,
  marked = false,
  variant = "panel",
  onToggled,
}: {
  mediaId: number;
  marksCount?: number;
  marked?: boolean;
  /** overlay — значок поверх превью карточки, panel — кнопка в нижней панели lightbox. */
  variant?: "overlay" | "panel";
  onToggled?: (state: { marked: boolean; marksCount: number }) => void;
}) {
  const [isMarked, setIsMarked] = useState(marked);
  const [count, setCount] = useState(marksCount);
  const [busy, setBusy] = useState(false);

  // Данные могут прийти заново (перезагрузка страницы/новая выборка)
  useEffect(() => {
    setIsMarked(marked);
    setCount(marksCount);
  }, [mediaId, marked, marksCount]);

  async function toggle() {
    if (busy) return;
    setBusy(true);
    try {
      const res = await apiPost<MarkResult>(`/api/v1/media/${mediaId}/mark`);
      setIsMarked(res.marked);
      setCount(res.marks_count);
      onToggled?.({ marked: res.marked, marksCount: res.marks_count });
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      if (status === 401) {
        if (window.confirm("Метки доступны аккаунту. Войти?")) {
          window.location.assign("/login");
        }
      } else {
        window.alert("Не удалось поставить метку. Попробуйте позже.");
      }
    } finally {
      setBusy(false);
    }
  }

  if (variant === "overlay") {
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          void toggle();
        }}
        disabled={busy}
        title={isMarked ? "Снять метку" : "Поставить метку"}
        aria-pressed={isMarked}
        className={`inline-flex items-center gap-1 rounded-[3px] px-1.5 py-0.5 font-mono text-[10px] backdrop-blur-sm transition-colors ${
          isMarked
            ? "bg-accent-primary/85 text-ink-primary"
            : "bg-black/60 text-text-secondary hover:text-text-primary"
        }`}
      >
        <TagIcon className="h-3 w-3" />
        {formatCompact(count)}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={() => void toggle()}
      disabled={busy}
      title={isMarked ? "Снять метку («отличный контент»)" : "Отметить как отличный контент"}
      aria-pressed={isMarked}
      className={`inline-flex items-center gap-1.5 rounded px-2.5 py-1.5 font-mono text-[11px] transition-colors ${
        isMarked
          ? "bg-accent-primary/15 text-accent-primary"
          : "text-text-secondary hover:text-text-primary"
      }`}
    >
      {busy ? <SpinnerIcon className="h-3.5 w-3.5" /> : <TagIcon className="h-3.5 w-3.5" />}
      {isMarked ? "отмечено" : "метка"}
      <span className="tabular-nums text-text-muted">{formatCompact(count)}</span>
    </button>
  );
}
