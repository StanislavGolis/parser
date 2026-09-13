"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { trackEvent } from "@/lib/track";

interface FilterChipsProps {
  /** Варианты типа контента: пустое значение — «всё». */
  typeOptions: Array<{ value: string; label: string }>;
  /** Показывать чип «без подписки» (файлы без premium). */
  showFree?: boolean;
  ariaLabel?: string;
}

/**
 * Чипы фильтра витрины главной: тип контента и «без подписки».
 * Пишут параметры в URL — фильтрацию делает сервер (SSR + кэш), поэтому
 * страница остаётся ссылочной (можно делиться конкретным фильтром).
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
  const free = params.get("free") === "1";

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
    push(next);
  }

  function toggleFree() {
    const next = new URLSearchParams(params.toString());
    if (free) next.delete("free");
    else next.set("free", "1");
    push(next);
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
        <button
          type="button"
          onClick={toggleFree}
          aria-pressed={free}
          title="Показать только файлы, доступные без подписки"
          className={`filter-btn font-mono text-[11px] ${free ? "filter-btn-active" : ""}`}
        >
          без подписки
        </button>
      ) : null}
    </div>
  );
}
