"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { readHidePremium, writeHidePremium } from "@/lib/prefs";
import { trackEvent } from "@/lib/track";

/**
 * Чекбокс «скрыть премиум»: убирает из лент файлы, доступные только по подписке.
 *
 * Настройка личная и хранится в cookie (`dv_hide_premium`), а не в URL: так она
 * действует на всех лентах и не плодит адресов-дубликатов. Фильтрует сервер —
 * после переключения просим его перечитать cookie (`router.refresh`).
 */
export default function HidePremiumToggle({ className = "" }: { className?: string }) {
  const router = useRouter();

  // Cookie читаем после монтирования: на сервере её нет (иначе SSR и первый
  // рендер разошлись бы).
  const [on, setOn] = useState(false);
  useEffect(() => setOn(readHidePremium()), []);

  function toggle(next: boolean) {
    writeHidePremium(next);
    setOn(next);
    trackEvent("filter_hide_premium", next ? "on" : "off");
    router.refresh();
  }

  return (
    <label
      className={`filter-btn inline-flex cursor-pointer items-center gap-1.5 font-mono text-[11px] ${className}`}
      title="Убрать из лент премиум-файлы"
    >
      <input
        type="checkbox"
        checked={on}
        onChange={(e) => toggle(e.target.checked)}
        className="h-3 w-3 cursor-pointer accent-accent-primary"
      />
      скрыть премиум
    </label>
  );
}
