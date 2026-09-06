"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { LockIcon } from "@/components/icons";
import { formatNumber } from "@/lib/format";
import type { Board } from "@/lib/types";

type Filter = "all" | "public" | "private";

const FILTERS: Array<{ value: Filter; label: string }> = [
  { value: "all", label: "ВСЕ" },
  { value: "public", label: "ПУБЛИЧНЫЕ" },
  { value: "private", label: "ПРИВАТНЫЕ" },
];

/** Главная = «Доски»: каталог разделов-архивов со статусами. */
export default function BoardsCatalog({ boards }: { boards: Board[] }) {
  const [filter, setFilter] = useState<Filter>("all");

  const visible = useMemo(
    () =>
      boards.filter((b) =>
        filter === "private" ? b.is_private : filter === "public" ? !b.is_private : true,
      ),
    [boards, filter],
  );

  if (boards.length === 0) {
    return (
      <div className="rounded border border-dashed border-line py-20 text-center">
        <p className="font-mono text-xs uppercase tracking-widest text-text-muted">
          архив пуст
        </p>
        <p className="mt-2 text-sm text-text-secondary">
          Разделы появятся после первого прохода парсера или добавления в админке.
        </p>
      </div>
    );
  }

  return (
    <div>
      {/* Фильтры */}
      <div className="mb-5 flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => setFilter(f.value)}
            className={`filter-btn font-mono text-[11px] ${
              filter === f.value ? "filter-btn-active" : ""
            }`}
          >
            {f.label}
          </button>
        ))}
        <span className="ml-auto font-mono text-[11px] text-text-muted">
          {formatNumber(visible.length)} показано
        </span>
      </div>

      {/* Сетка досок */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
        {visible.map((b) => (
          <Link
            key={b.id}
            href={`/board/${b.slug}`}
            className="group flex flex-col justify-between rounded border border-line bg-ink-secondary p-4 transition-colors duration-150 hover:border-accent-primary"
          >
            <div>
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-base font-bold uppercase tracking-wider text-text-primary">
                  /{b.slug}
                </span>
                {b.is_private ? (
                  <span className="badge badge-warn">
                    <LockIcon className="h-2.5 w-2.5" />
                    приватная
                  </span>
                ) : null}
              </div>
              <p className="mt-1 truncate text-sm text-text-secondary" title={b.title || b.slug}>
                {b.title || b.slug}
              </p>
            </div>

            <div className="mt-4 flex items-center justify-between">
              <span className="font-mono text-[11px] text-text-muted">
                {formatNumber(b.media_count)} файлов
              </span>
              {b.is_private ? (
                <span className="font-mono text-[11px] text-accent-warning">доступ по коду</span>
              ) : (
                <span className="font-mono text-[11px] text-text-muted transition-colors group-hover:text-accent-primary">
                  открыть →
                </span>
              )}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
