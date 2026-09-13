"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { readHidePremium, writeHidePremium } from "@/lib/prefs";
import { trackEvent } from "@/lib/track";

interface FilterChipsProps {
  /** Варианты типа контента: пустое значение — «всё». */
  typeOptions: Array<{ value: string; label: string }>;
  /** Показывать чекбокс «скрыть премиум» (файлы без premium). */
  showFree?: boolean;
  ariaLabel?: string;
}

/**
 * Чипы фильтра витрины: тип контента (пишется в URL — фильтр ссылочный) и
 * чекбокс «скрыть премиум» (хранится в cookie — это личная настройка, её не
 * нужно таскать в адресе и в canonical).
 */
export default function FilterChips({
  typeOptions,
  showFree = true,
  ariaLabel = "Фильтр витрины",
}: FilterChipsProps) {
  const pathname = usePathname();
  const router = useRouter();
  const params = useSearchParams();

  const type = params.get("type") ?? "";

  // Cookie читаем после монтирования: на сервере её нет, иначе SSR и первый
  // рендер разошлись бы (hydration mismatch).
  const [hidePremium, setHidePremium] = useState(false);
  useEffect(() => setHidePremium(readHidePremium()), []);

  function push(next: URLSearchParams) {
    const qs = next.toString();
    // Событие для статистики: видно, какими фильтрами пользуются
    trackEvent("filter_click", qs ? `${pathname}?${qs}` : pathname);
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  function selectType(value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set("type", value);
    else next.delete("type");
    // Переходим на cookie-модель: старый параметр `free` из ссылок больше не пишем
    next.delete("free");
    push(next);
  }

  function toggleHidePremium(on: boolean) {
    writeHidePremium(on);
    setHidePremium(on);
    trackEvent("filter_hide_premium", on ? "on" : "off");
    // Ленту фильтрует сервер: просим его перечитать cookie
    router.refresh();
  }

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={ariaLabel}>
      {typeOptions.map((opt) => (
        <button
          key={opt.value || "all"}
          type="button"
          onClick={() => selectType(opt.value)}
          aria-pressed={type === opt.value}
          className={`filter-btn font-mono text-[11px] ${
            type === opt.value ? "filter-btn-active" : ""
          }`}
        >
          {opt.label}
        </button>
      ))}
      {showFree ? (
        <label
          className="filter-btn inline-flex cursor-pointer items-center gap-1.5 font-mono text-[11px]"
          title="Убрать из лент премиум-файлы — останутся только доступные без подписки"
        >
          <input
            type="checkbox"
            checked={hidePremium}
            onChange={(e) => toggleHidePremium(e.target.checked)}
            className="h-3 w-3 cursor-pointer accent-accent-primary"
          />
          скрыть премиум
        </label>
      ) : null}
    </div>
  );
}
