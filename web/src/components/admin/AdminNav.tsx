"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/** Вкладки админки. Вкладка «Контент» владеет и страницами тредов раздела. */
const TABS: Array<{ href: string; label: string; match: (p: string) => boolean }> = [
  { href: "/admin", label: "Обзор", match: (p) => p === "/admin" },
  {
    href: "/admin/content",
    label: "Контент",
    match: (p) => p.startsWith("/admin/content") || p.startsWith("/admin/boards"),
  },
  { href: "/admin/sources", label: "Источники", match: (p) => p.startsWith("/admin/sources") },
  { href: "/admin/feedback", label: "Обратная связь", match: (p) => p.startsWith("/admin/feedback") },
  { href: "/admin/reports", label: "Жалобы", match: (p) => p.startsWith("/admin/reports") },
  { href: "/admin/telegram", label: "Telegram", match: (p) => p.startsWith("/admin/telegram") },
  { href: "/admin/users", label: "Пользователи", match: (p) => p.startsWith("/admin/users") },
  { href: "/admin/stats", label: "Статистика", match: (p) => p.startsWith("/admin/stats") },
];

/** Навигация админки: вкладки + выход. Подсветка — по текущему адресу. */
export default function AdminNav({ onLogout }: { onLogout: () => void }) {
  const pathname = usePathname();

  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-line pb-2">
      <nav className="flex flex-wrap items-stretch gap-1" aria-label="Разделы админки">
        {TABS.map((tab) => {
          const active = tab.match(pathname);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={`inline-flex items-center border-b-2 px-3 py-2 text-sm transition-colors duration-150 ${
                active
                  ? "border-accent-primary font-semibold text-text-primary"
                  : "border-transparent text-text-secondary hover:text-text-primary"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>

      <div className="flex items-center gap-2">
        <Link href="/" className="btn-ghost px-3 py-1.5 text-xs" title="Открыть публичный сайт">
          Сайт →
        </Link>
        <button type="button" onClick={onLogout} className="btn-ghost px-3 py-1.5 text-xs">
          Выйти
        </button>
      </div>
    </div>
  );
}
