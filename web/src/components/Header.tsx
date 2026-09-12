"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import AuthMenu from "@/components/AuthMenu";

const NAV = [
  {
    href: "/",
    label: "Доски",
    match: (p: string) => p === "/" || p.startsWith("/board"),
  },
  { href: "/new", label: "Новинки", match: (p: string) => p === "/new" },
  { href: "/top", label: "Популярное", match: (p: string) => p === "/top" },
  { href: "/favorites", label: "Избранное", match: (p: string) => p.startsWith("/favorites") },
  { href: "/search", label: "Поиск", match: (p: string) => p.startsWith("/search") },
];

export default function Header() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-ink-primary/95 backdrop-blur">
      <div className="mx-auto flex h-16 w-full max-w-[1400px] items-center justify-between gap-6 px-4 sm:px-6">
        {/* Логотип */}
        <Link href="/" className="flex shrink-0 items-baseline gap-3" aria-label="DREDGE — на главную">
          <span className="font-mono text-lg font-bold uppercase tracking-[0.15em] text-text-primary">
            DREDGE
          </span>
          <span className="hidden font-mono text-[11px] lowercase text-text-muted lg:inline">
            архив // отбор // доступ
          </span>
        </Link>

        {/* Desktop-навигация + вход */}
        <div className="flex items-center gap-3">
          <nav className="flex h-16 items-stretch gap-1" aria-label="Основная навигация">
            {NAV.map((item) => {
              const active = item.match(pathname);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`inline-flex items-center border-b-2 px-3 text-sm transition-colors duration-150 ${
                    active
                      ? "border-accent-primary font-semibold text-text-primary"
                      : "border-transparent text-text-secondary hover:text-text-primary"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <AuthMenu />
        </div>
      </div>
    </header>
  );
}

