"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { apiSend } from "@/lib/api";
import { notifyAuthChanged, onAuthChanged } from "@/lib/authEvents";
import type { UserOut } from "@/lib/types";

/** Кто вошёл: «Войти» / email + «Выйти». */
export default function AuthMenu() {
  const router = useRouter();
  const [user, setUser] = useState<UserOut | null>(null);
  const [ready, setReady] = useState(false);

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

  async function logout() {
    try {
      await apiSend("/api/v1/auth/logout", { method: "POST" });
    } catch {
      /* всё равно сбрасываем локальное состояние */
    }
    setUser(null);
    // Серверные компоненты (премиум-превью, метки) перерисовываем, а клиентские
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

  return (
    <div className="flex items-center gap-2">
      <Link
        href="/profile"
        className={`hidden max-w-[160px] items-center gap-1 truncate rounded px-1 py-1 font-mono text-[11px] transition-colors sm:inline-flex ${
          user.is_premium
            ? "text-accent-warning hover:text-accent-warning/80"
            : "text-text-muted hover:text-text-primary"
        }`}
        title={user.is_premium ? "Премиум активен — открыть профиль" : "Открыть профиль"}
      >
        {user.is_premium ? "★" : null}
        <span className="truncate">{user.email}</span>
      </Link>
      <Link href="/profile" className="btn-ghost px-3 py-1.5 text-xs">
        Профиль
      </Link>
      <button type="button" onClick={() => void logout()} className="btn-ghost px-3 py-1.5 text-xs">
        Выйти
      </button>
    </div>
  );
}
