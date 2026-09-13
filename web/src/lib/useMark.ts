"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiPost } from "./api";
import { trackEvent } from "./track";
import type { MarkResult } from "./types";

/** Состояние и переключатель метки («отличный контент») для одного файла. */
export interface MarkToggleState {
  marked: boolean;
  marksCount: number;
  busy: boolean;
  /** Последнее действие — для тоста/подсветки (null до первого переключения). */
  lastAction: "marked" | "unmarked" | null;
  toggle: () => Promise<void>;
}

/**
 * Общий хук метки: используется и кнопкой (`MarkButton`), и горячей клавишей
 * в lightbox, чтобы состояние было единым (иначе пробел и клик разойдутся).
 * Анониму предлагает войти; остальные ошибки — alert.
 */
export function useMarkToggle(
  mediaId: number,
  initialMarked: boolean,
  initialCount: number,
): MarkToggleState {
  const [marked, setMarked] = useState(initialMarked);
  const [marksCount, setMarksCount] = useState(initialCount);
  const [busy, setBusy] = useState(false);
  const [lastAction, setLastAction] = useState<"marked" | "unmarked" | null>(null);

  // Данные могут прийти заново (перезагрузка/другая выборка) — синхронизируемся
  useEffect(() => {
    setMarked(initialMarked);
    setMarksCount(initialCount);
    setLastAction(null);
  }, [mediaId, initialMarked, initialCount]);

  const toggle = useCallback(async () => {
    if (busy || !mediaId) return;
    setBusy(true);
    try {
      const res = await apiPost<MarkResult>(`/api/v1/media/${mediaId}/mark`);
      setMarked(res.marked);
      setMarksCount(res.marks_count);
      setLastAction(res.marked ? "marked" : "unmarked");
      // Событие для статистики: сколько меток ставят и снимают
      trackEvent(res.marked ? "mark_add" : "mark_remove");
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
  }, [busy, mediaId]);

  return { marked, marksCount, busy, lastAction, toggle };
}
