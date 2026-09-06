"use client";

import { useEffect } from "react";

import { apiGet } from "@/lib/api";
import type { ViewResult } from "@/lib/types";

/**
 * Отмечает просмотр файла на бэкенде (GET /media/{id}/view) при открытии
 * страницы из браузера. Ничего не рендерит. Ошибки сети/rate-limit молча
 * пропускаются — просмотр не критичен.
 */
export default function TrackView({ mediaId }: { mediaId: number }) {
  useEffect(() => {
    apiGet<ViewResult>(`/api/v1/media/${mediaId}/view`).catch(() => {
      /* молча пропускаем */
    });
  }, [mediaId]);

  return null;
}
