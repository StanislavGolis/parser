"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, apiSend } from "@/lib/api";
import type { UserOut } from "@/lib/types";

/** Вход/регистрация: доступ к оригиналам файлов. */
export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiSend<UserOut>(`/api/v1/auth/${mode}`, {
        method: "POST",
        body: { email, password },
      });
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? (err.detail ?? err.message) : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="container-site max-w-md py-10">
      <h1 className="text-xl font-bold text-text-primary">
        {mode === "login" ? "Вход" : "Регистрация"}
      </h1>
      <p className="mt-1 text-sm text-text-secondary">
        Оригиналы файлов доступны только зарегистрированным пользователям.
      </p>

      <form onSubmit={submit} className="mt-6 flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          Email
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded border border-line bg-ink-secondary px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary"
            autoComplete="email"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          Пароль
          <input
            type="password"
            required
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded border border-line bg-ink-secondary px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
        </label>

        {error ? <p className="text-sm text-accent-danger">{error}</p> : null}

        <button type="submit" disabled={busy} className="btn-primary mt-1">
          {busy ? "Подождите…" : mode === "login" ? "Войти" : "Зарегистрироваться"}
        </button>
      </form>

      <div className="mt-4 text-sm text-text-secondary">
        {mode === "login" ? (
          <>
            Нет аккаунта?{" "}
            <button type="button" onClick={() => setMode("register")} className="text-accent-primary hover:underline">
              Зарегистрироваться
            </button>
          </>
        ) : (
          <>
            Уже есть аккаунт?{" "}
            <button type="button" onClick={() => setMode("login")} className="text-accent-primary hover:underline">
              Войти
            </button>
          </>
        )}
      </div>

      <p className="mt-6 text-xs text-text-muted">
        <Link href="/" className="hover:text-text-secondary">
          ← На главную
        </Link>
      </p>
    </div>
  );
}
