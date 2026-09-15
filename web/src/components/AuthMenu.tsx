"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  BookmarkIcon,
  ChevronDownIcon,
  StarIcon,
  TagIcon,
} from "@/components/icons";
import { apiSend } from "@/lib/api";
import { notifyAuthChanged, onAuthChanged } from "@/lib/authEvents";
import { BUY_CTA_EXTERNAL, BUY_CTA_URL } from "@/lib/env";
import type { UserOut } from "@/lib/types";

/** Срок подписки коротко: «до 20.10». */
function untilShort(iso: string | null): string {
  if (!iso) return "активна";
  const date = new Date(iso.length <= 10 ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(date.getTime())) return "активна";
  const pad = (value: number) => String(value).padStart(2, "0");
  return `до ${pad(date.getDate())}.${pad(date.getMonth() + 1)}`;
}

/** Короткое имя для шапки: почту обрезаем до «@», ник оставляем как есть. */
function shortName(user: UserOut): string {
  const name = user.display_name || "";
  const at = name.indexOf("@");
  return at > 0 ? name.slice(0, at) : name;
}

/**
 * Блок аккаунта в шапке: кнопка подписки + меню пользователя.
 *
 * Раньше тут было три элемента (почта, «Профиль», «Выйти»), причём почта вела туда же,
 * куда кнопка «Профиль». Теперь один компактный блок: рядом кнопка подписки (нет
 * подписки — «Купить подписку», есть — «★ до 20.10»), а по клику на имя открывается
 * меню с профилем, закладками, тарифами, «продолжить» и выходом.
 */
export default function AuthMenu() {
  const router = useRouter();
  const [user, setUser] = useState<UserOut | null>(null);
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    try {
      setUser(await apiSend<UserOut>("/api/v1/auth/me"));
    } catch {
      setUser(null);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    void load();
    // Вход/выход на других страницах (форма входа, профиль) — обновляем шапку
    return onAuthChanged(() => void load());
  }, [load]);

  // Закрываем меню по клику вне и по Esc (иначе оно «залипает» на странице)
  useEffect(() => {
    if (!open) return;
    function onClick(event: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);


  async function logout() {
    try {
      await apiSend("/api/v1/auth/logout", { method: "POST" });
    } catch {
      /* всё равно сбрасываем локальное состояние */
    }
    setOpen(false);
    setUser(null);
    // Серверные компоненты (премиум-превью, закладки) перерисовываем, а клиентские
    // о выходе оповещаем событием — иначе шапка жила бы со старым именем.
    notifyAuthChanged();
    router.refresh();
  }

  if (!ready) return null;

  if (!user) {
    return (
      <Link href="/login" className="btn-ghost px-3 py-1.5 text-xs">
        Войти
      </Link>
    );
  }

  const initial = (shortName(user).replace(/^@/, "").charAt(0) || "?").toUpperCase();

  return (
    <div className="flex items-center gap-2">
      {/* Подписка: нет — «Купить подписку» (ведёт в бота), есть — срок действия.
          На телефоне кнопку не показываем: там для этого есть нижнее меню «Тарифы». */}
      {user.is_premium ? (
        <Link
          href="/subscribe"
          className="hidden items-center gap-1 rounded border border-accent-warning/40 px-2.5 py-1.5 font-mono text-[11px] text-accent-warning transition-colors hover:border-accent-warning sm:inline-flex"
          title="Подписка активна — тарифы и продление"
        >
          <StarIcon className="h-3.5 w-3.5" />
          {untilShort(user.premium_until)}
        </Link>
      ) : (
        <a
          href={BUY_CTA_URL}
          target={BUY_CTA_EXTERNAL ? "_blank" : undefined}
          rel="noreferrer"
          className="btn-primary hidden px-3 py-1.5 text-xs sm:inline-flex"
          title="Купить подписку: приватные разделы, скачивание, без рекламы"
        >
          <StarIcon className="h-3.5 w-3.5" />
          Купить подписку
        </a>
      )}

      {/* Аккаунт: одна кнопка вместо трёх («почта», «Профиль», «Выйти») */}
      <div ref={boxRef} className="relative">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-haspopup="menu"
          aria-expanded={open}
          title={user.display_name}
          className={`inline-flex items-center gap-2 rounded border px-2 py-1.5 text-xs transition-colors ${
            open
              ? "border-accent-primary text-text-primary"
              : "border-line text-text-secondary hover:text-text-primary"
          }`}
        >
          <span
            aria-hidden
            className={`flex h-5 w-5 items-center justify-center rounded-sm font-mono text-[10px] ${
              user.is_premium
                ? "bg-accent-warning/20 text-accent-warning"
                : "bg-ink-tertiary text-text-secondary"
            }`}
          >
            {initial}
          </span>
          <span className="hidden max-w-[120px] truncate font-mono text-[11px] sm:inline">
            {shortName(user)}
          </span>
          <ChevronDownIcon
            className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`}
          />
        </button>

        {open ? (
          <div
            role="menu"
            className="absolute right-0 top-full z-50 mt-2 w-56 rounded border border-line bg-ink-secondary p-1 shadow-lg"
          >
            <p
              className="truncate px-2 py-1.5 font-mono text-[10px] text-text-muted"
              title={user.display_name}
            >
              {user.display_name}
            </p>
            <Link
              href="/profile"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="block rounded px-2 py-1.5 text-xs text-text-secondary hover:bg-ink-tertiary hover:text-text-primary"
            >
              Профиль
            </Link>
            <Link
              href="/marks"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 rounded px-2 py-1.5 text-xs text-text-secondary hover:bg-ink-tertiary hover:text-text-primary"
            >
              <BookmarkIcon className="h-3.5 w-3.5" />
              Мои закладки
            </Link>
            <Link
              href="/subscribe"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 rounded px-2 py-1.5 text-xs text-text-secondary hover:bg-ink-tertiary hover:text-text-primary"
            >
              <TagIcon className="h-3.5 w-3.5" />
              Подписка и тарифы
            </Link>
            <button
              type="button"
              role="menuitem"
              onClick={() => void logout()}
              className="mt-1 block w-full rounded border-t border-line px-2 py-1.5 text-left text-xs text-text-secondary hover:bg-ink-tertiary hover:text-text-primary"
            >
              Выйти
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
