"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import AuthMenu from "@/components/AuthMenu";
import { SearchIcon } from "@/components/icons";

const NAV = [
  {
    href: "/",
    label: "Новое",
    match: (p: string) => p === "/",
  },
  {
    href: "/boards",
    label: "Разделы",
    match: (p: string) => p === "/boards" || p.startsWith("/board"),
  },
  { href: "/top", label: "Топ", match: (p: string) => p === "/top" },
  // Личный раздел: на средних экранах уходит в меню аккаунта, чтобы шапка не жмётся
  {
    href: "/marks",
    label: "Закладки",
    match: (p: string) => p.startsWith("/marks"),
    wide: true,
  },
];

/**
 * Верхняя шапка.
 *
 * На мобильных здесь только название сайта и вход: навигация живёт в нижнем меню
 * (`MobileNav`). Длинное меню в шапке занимало пол-экрана, из-за чего при скролле
 * прыгала панель браузера и контент «гулял». Blur на мобильных тоже не используем:
 * `backdrop-filter` заметно тормозит скролл на слабых устройствах.
 */
export default function Header() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-ink-primary md:bg-ink-primary/95 md:backdrop-blur">
      <div className="mx-auto flex h-12 w-full max-w-[1400px] items-center justify-between gap-6 px-4 md:h-16 sm:px-6">
        {/* Логотип */}
        <Link
          href="/"
          className="flex shrink-0 items-baseline gap-3"
          aria-label="DREDGER — на главную"
        >
          <span className="font-mono text-base font-bold uppercase tracking-[0.15em] text-text-primary md:text-lg">
            DREDGER
          </span>
          <span className="hidden font-mono text-[11px] lowercase text-text-muted lg:inline">
            архив // отбор // доступ
          </span>
        </Link>

        <div className="flex items-center gap-3">
          {/* Меню только с планшета и шире: на телефоне навигация снизу */}
          <nav className="hidden h-16 items-stretch gap-1 md:flex" aria-label="Основная навигация">
            {NAV.map((item) => {
              const active = item.match(pathname);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`${
                    item.wide ? "hidden lg:inline-flex" : "inline-flex"
                  } items-center border-b-2 px-3 text-sm transition-colors duration-150 ${
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
          {/* Поиск — иконкой: отдельный пункт меню перегружал шапку */}
          <Link
            href="/search"
            aria-label="Поиск по архиву"
            title="Поиск по архиву"
            className={`inline-flex h-9 w-9 items-center justify-center rounded transition-colors ${
              pathname.startsWith("/search")
                ? "text-accent-primary"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            <SearchIcon className="h-5 w-5" />
          </Link>
          <AuthMenu />
        </div>
      </div>
    </header>
  );
}

