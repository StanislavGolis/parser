"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { ImageIcon, LayersIcon, SearchIcon, StarIcon, TagIcon } from "@/components/icons";

const ITEMS = [
  {
    href: "/",
    label: "Доски",
    Icon: LayersIcon,
    match: (p: string) => p === "/" || p.startsWith("/board"),
  },
  { href: "/new", label: "Новинки", Icon: ImageIcon, match: (p: string) => p === "/new" },
  { href: "/top", label: "Топ", Icon: StarIcon, match: (p: string) => p === "/top" },
  {
    href: "/marks",
    label: "Метки",
    Icon: TagIcon,
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
