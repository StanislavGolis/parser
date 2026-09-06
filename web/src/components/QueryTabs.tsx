"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

export interface TabOption {
  value: string;
  label: string;
}

interface QueryTabsProps {
  /** Имя query-параметра, которым управляет группа вкладок. */
  param: string;
  options: TabOption[];
  /** Значение по умолчанию, если параметр не задан. */
  defaultValue?: string;
  ariaLabel: string;
}

/**
 * Группа вкладок-ссылок, сохраняющая остальные query-параметры.
 * Изменение параметра перезагружает данные на сервере (SSR + Data Cache).
 */
export default function QueryTabs({ param, options, defaultValue = "", ariaLabel }: QueryTabsProps) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();

  const raw = searchParams.get(param) ?? "";
  const current = options.some((o) => o.value === raw) ? raw : defaultValue;

  function select(value: string) {
    const p = new URLSearchParams(searchParams.toString());
    if (value && value !== defaultValue) p.set(param, value);
    else p.delete(param);
    const qs = p.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className="inline-flex flex-wrap items-center gap-1 rounded-xl border border-neutral-800 bg-neutral-900/70 p-1"
    >
      {options.map((opt) => {
        const active = current === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => select(opt.value)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              active
                ? "bg-amber-500 text-neutral-950"
                : "text-neutral-300 hover:bg-neutral-800 hover:text-white"
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
