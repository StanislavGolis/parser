"use client";

import { useEffect } from "react";

import { LAST_VISIT_COOKIE, LAST_VISIT_MAX_AGE } from "@/lib/visit";

/**
 * Отмечает момент визита в cookie (можно без middleware): при следующем заходе
 * серверный рендер главной покажет «+N новых файлов с <дата>».
 * Компонент ничего не рисует — только побочный эффект.
 */
export default function VisitStamp() {
  useEffect(() => {
    const value = new Date().toISOString();
    document.cookie = `${LAST_VISIT_COOKIE}=${value}; path=/; max-age=${LAST_VISIT_MAX_AGE}; samesite=lax`;
  }, []);

  return null;
}
