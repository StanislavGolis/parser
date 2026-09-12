"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { apiSend } from "@/lib/api";
import type { UserOut } from "@/lib/types";

/** Кто вошёл: «Войти» / email + «Выйти». */
export default function AuthMenu() {
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
  }, [load]);

  async function logout() {
    try {
      await apiSend("/api/v1/auth/logout", { method: "POST" });
    } catch {
      /* всё равно сбрасываем локальное состояние */
    }
    setUser(null);
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
      <span className="hidden max-w-[160px] truncate font-mono text-[11px] text-text-muted sm:inline" title={user.email}>
        {user.email}
      </span>
      <button type="button" onClick={() => void logout()} className="btn-ghost px-3 py-1.5 text-xs">
        Выйти
      </button>
    </div>
  );
}
