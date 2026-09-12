"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ApiError, apiPost } from "@/lib/api";

/**
 * Страница сброса пароля админа по ссылке из письма (`/admin/reset?token=…`).
 *
 * Токен читаем из адреса вручную (без useSearchParams), чтобы страница работала
 * как обычный клиентский компонент без Suspense-обвязки.
 */
export default function AdminResetPage() {
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setToken(params.get("token") ?? "");
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 10) {
      setError("Пароль должен быть не короче 10 символов");
      return;
    }
    if (password !== repeat) {
      setError("Пароли не совпадают");
      return;
    }
    setBusy(true);
    try {
      const out = await apiPost<{ email: string }>("/api/v1/admin/auth/reset", {
        token,
        password,
      });
      setDone(out.email);
      setPassword("");
      setRepeat("");
    } catch (err) {
      setError(
        err instanceof ApiError && err.detail ? err.detail : "Не удалось сменить пароль",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md py-10">
      <h2 className="text-xl font-bold">Смена пароля админа</h2>

      {done ? (
        <div className="mt-4 flex flex-col gap-3">
          <p className="text-sm text-accent-secondary">
            Пароль для {done} обновлён, прежние сессии сброшены.
          </p>
          <Link href="/admin" className="btn-primary text-center">
            Перейти ко входу
          </Link>
        </div>
      ) : (
        <>
          <p className="mt-1 text-sm text-text-secondary">
            Ссылка одноразовая. После смены пароля войдите в админку по email и новому
            паролю.
          </p>
          {!token ? (
            <p className="mt-4 text-sm text-accent-danger">
              В ссылке нет токена — запросите новую на странице входа.
            </p>
          ) : null}
          <form onSubmit={submit} className="mt-5 flex flex-col gap-3">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Новый пароль (мин. 10 символов)"
              autoFocus
              className="rounded border border-line bg-ink-secondary px-3 py-2 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-accent-primary"
            />
            <input
              type="password"
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
              placeholder="Повторите пароль"
              className="rounded border border-line bg-ink-secondary px-3 py-2 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-accent-primary"
            />
            <button type="submit" disabled={busy || !token} className="btn-primary">
              {busy ? "Сохраняем…" : "Сменить пароль"}
            </button>
            {error ? <p className="text-sm text-accent-danger">{error}</p> : null}
          </form>
        </>
      )}

      <p className="mt-5 text-xs text-text-muted">
        Если почта не настроена, пароль можно сменить командой на сервере:{" "}
        <code>python -m src.cli.admin set-password --email …</code>
      </p>
    </div>
  );
}
