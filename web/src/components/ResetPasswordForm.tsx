"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ApiError, apiPost } from "@/lib/api";

const INPUT_CLASS =
  "rounded border border-line bg-ink-secondary px-3 py-2 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-accent-primary";

function errText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return err.detail;
  return err instanceof Error ? err.message : "Ошибка";
}

/**
 * Смена пароля по ссылке из письма.
 *
 * Токен читаем из адреса вручную (без useSearchParams) — страница остаётся
 * простым клиентским компонентом без Suspense-обвязки.
 */
export default function ResetPasswordForm() {
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const value = new URLSearchParams(window.location.search).get("token") ?? "";
    setToken(value);
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < 6) {
      setError("Пароль короче 6 символов");
      return;
    }
    if (password !== repeat) {
      setError("Пароли не совпадают");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiPost<{ ok: boolean; email: string }>("/api/v1/auth/reset", { token, password });
      setDone(true);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div>
        <h1 className="text-xl font-bold">Пароль изменён</h1>
        <p className="mt-2 text-sm text-text-secondary">
          Теперь можно войти с новым паролем. Все прежние сессии закрыты.
        </p>
        <Link href="/login" className="btn-primary mt-5 inline-flex">
          Войти
        </Link>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-xl font-bold">Смена пароля</h1>
      <p className="mt-1 text-sm text-text-secondary">
        Ссылка одноразовая и действует ограниченное время. Придумайте новый пароль.
      </p>

      {!token ? (
        <p className="mt-5 rounded border border-accent-danger/40 bg-accent-danger/10 px-3 py-2 text-sm text-accent-danger">
          В адресе нет токена — откройте ссылку из письма целиком.
        </p>
      ) : null}

      <form onSubmit={submit} className="mt-5 flex flex-col gap-3">
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Новый пароль"
          autoFocus
          className={INPUT_CLASS}
        />
        <input
          type="password"
          value={repeat}
          onChange={(e) => setRepeat(e.target.value)}
          placeholder="Повторите пароль"
          className={INPUT_CLASS}
        />
        <button
          type="submit"
          disabled={busy || !token || !password || !repeat}
          className="btn-primary"
        >
          {busy ? "Сохраняем…" : "Сменить пароль"}
        </button>
        {error ? <p className="text-sm text-accent-danger">{error}</p> : null}
      </form>

      <p className="mt-6 text-xs text-text-muted">
        <Link href="/login" className="text-accent-primary hover:underline">
          Вернуться ко входу
        </Link>
      </p>
    </div>
  );
}
