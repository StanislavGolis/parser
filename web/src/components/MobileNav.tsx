"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { BookmarkIcon, ImageIcon, LayersIcon, StarIcon } from "@/components/icons";

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
  // «Поиск» и «Тарифы» из нижнего меню убраны — они и так под рукой на телефоне:
  // поиск иконкой в шапке (она липкая и видна всегда), тарифы — пунктом «Подписка
  // и тарифы» в меню аккаунта. Шесть пунктов не влезали: подписи сжимались, и
  // вместо четырёх крупных кнопок получалась полоса мелких, куда трудно попасть.
];

/**
 * Нижняя навигация на мобильных.
 *
 * Она — единственное меню на телефоне, поэтому держим её компактной и без
 * `backdrop-blur`: размытие под фиксированной панелью тормозит скролл. Учитываем
 * «безопасную зону» iPhone — иначе панель перекрывает системная полоса.
 */
export default function MobileNav() {
  const pathname = usePathname();

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 grid h-[calc(3.5rem+env(safe-area-inset-bottom))] grid-cols-4 border-t border-line bg-ink-secondary pb-[env(safe-area-inset-bottom)] md:hidden"
      aria-label="Мобильная навигация"
    >
      {ITEMS.map(({ href, label, Icon, match }) => {
        const active = match(pathname);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            // Полоска сверху у активного пункта: на телефоне она читается быстрее,
            // чем цвет подписи, и сразу показывает, где мы находимся.
            className={`flex flex-col items-center justify-center gap-0.5 border-t-2 ${
              active ? "border-accent-primary" : "border-transparent"
            }`}
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
