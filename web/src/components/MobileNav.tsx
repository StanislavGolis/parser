"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { BookmarkIcon, ImageIcon, LayersIcon, SearchIcon, StarIcon } from "@/components/icons";

const ITEMS = [
  {
    href: "/",
    label: "Новое",
    Icon: ImageIcon,
    match: (p: string) => p === "/",
  },
  {
    href: "/boards",
    label: "Разделы",
    Icon: LayersIcon,
    match: (p: string) => p === "/boards" || p.startsWith("/board"),
  },
  { href: "/top", label: "Топ", Icon: StarIcon, match: (p: string) => p === "/top" },
  {
    href: "/marks",
    label: "Закладки",
    Icon: BookmarkIcon,
    match: (p: string) => p.startsWith("/marks"),
  },
  { href: "/search", label: "Поиск", Icon: SearchIcon, match: (p: string) => p.startsWith("/search") },
];

/** Нижняя навигация на мобильных (по ТЗ дизайна п.6). */
export default function MobileNav() {
  const pathname = usePathname();

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 grid h-14 grid-cols-5 border-t border-line bg-ink-secondary/95 backdrop-blur md:hidden"
      aria-label="Мобильная навигация"
    >
      {ITEMS.map(({ href, label, Icon, match }) => {
        const active = match(pathname);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className="flex flex-col items-center justify-center gap-0.5"
          >
            <Icon
              className={`h-5 w-5 ${active ? "text-accent-primary" : "text-text-muted"}`}
              aria-hidden
            />
            <span
              className={`font-mono text-[10px] uppercase tracking-wider ${
                active ? "text-text-primary" : "text-text-muted"
              }`}
            >
              {label}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}
