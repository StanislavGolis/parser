"use client";

import { useEffect, useState } from "react";

import { BookmarkIcon, SpinnerIcon } from "@/components/icons";
import { ApiError, apiPost } from "@/lib/api";
import type { FavoriteResult } from "@/lib/types";

/**
 * Избранное — личная подборка файлов (требует аккаунт).
 * Список доступен на странице `/favorites`.
 */
export default function FavoriteButton({
  mediaId,
  favorited = false,
  variant = "panel",
  onToggled,
}: {
  mediaId: number;
  favorited?: boolean;
  /** overlay — значок поверх превью карточки, panel — кнопка в нижней панели lightbox. */
  variant?: "overlay" | "panel";
  onToggled?: (favorited: boolean) => void;
}) {
  const [isFav, setIsFav] = useState(favorited);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setIsFav(favorited);
  }, [mediaId, favorited]);

  async function toggle() {
    if (busy) return;
    setBusy(true);
    try {
      const res = await apiPost<FavoriteResult>(`/api/v1/media/${mediaId}/favorite`);
      setIsFav(res.favorited);
      onToggled?.(res.favorited);
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      if (status === 401) {
        if (window.confirm("Избранное доступно аккаунту. Войти?")) {
          window.location.assign("/login");
        }
      } else {
        window.alert("Не удалось обновить избранное. Попробуйте позже.");
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
        title={isFav ? "Убрать из избранного" : "В избранное"}
        aria-pressed={isFav}
        className={`inline-flex items-center rounded-[3px] p-1.5 backdrop-blur-sm transition-colors ${
          isFav
            ? "bg-accent-warning/85 text-ink-primary"
            : "bg-black/60 text-text-secondary hover:text-text-primary"
        }`}
      >
        <BookmarkIcon className="h-3.5 w-3.5" />
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={() => void toggle()}
      disabled={busy}
      title={isFav ? "Убрать из избранного" : "Добавить в избранное"}
      aria-pressed={isFav}
      className={`inline-flex items-center gap-1.5 rounded px-2.5 py-1.5 font-mono text-[11px] transition-colors ${
        isFav ? "bg-accent-warning/15 text-accent-warning" : "text-text-secondary hover:text-text-primary"
      }`}
    >
      {busy ? <SpinnerIcon className="h-3.5 w-3.5" /> : <BookmarkIcon className="h-3.5 w-3.5" />}
      {isFav ? "в избранном" : "в избранное"}
    </button>
  );
}
