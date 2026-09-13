"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";

import { trackPageView } from "@/lib/track";

/**
 * Отмечает просмотры страниц для своей аналитики (админка → «Статистика»).
 * Ничего не рендерит; ошибки сети молча пропускаются.
 */
function PageTracker() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const query = searchParams.toString();

  useEffect(() => {
    if (pathname.startsWith("/admin")) return; // админку не считаем
    trackPageView(query ? `${pathname}?${query}` : pathname);
  }, [pathname, query]);

  return null;
}

export default function Tracker() {
  return (
    <Suspense fallback={null}>
      <PageTracker />
    </Suspense>
  );
}
