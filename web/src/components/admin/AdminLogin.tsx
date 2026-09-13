"use client";

import Link from "next/link";
import { useState } from "react";

import { ApiError, apiPost } from "@/lib/api";
import { writeAdminToken } from "@/lib/adminAuth";

type Mode = "password" | "forgot" | "token";

function errText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return err.detail;
  return err instanceof Error ? err.message : "Ошибка";
}

const INPUT_CLASS =
  "rounded border border-line bg-ink-secondary px-3 py-2 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-accent-primary";

/**
 * Вход в админку: email+пароль (основной), восстановление пароля письмом
 * и резервный вход по admin-токену. Пускает дальше через `writeAdminToken` —
 * гейт в layout админки подхватывает изменение и показывает панель.
 */
export default function AdminLogin() {
  const [mode, setMode] = useState<Mode>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tokenInput, setTokenInput] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
    setMessage(null);
  }

  /** Резервный вход: админ-токен из окружения сервера. */
  function submitToken(e: React.FormEvent) {
    e.preventDefault();
    const value = tokenInput.trim();
    if (!value) return;
    writeAdminToken(value);
  }

  /** Вход по email+паролю: в ответе приходит тот же ADMIN_TOKEN для панели. */
  async function submitPassword(e: React.FormEvent) {
    e.preventDefault();
    const mail = email.trim();
    if (!mail || !password) return;
    setBusy(true);
    setError(null);
    try {
      const out = await apiPost<{ email: string; token: string }>("/api/v1/admin/auth/login", {
        email: mail,
        password,
      });
      setPassword("");
      writeAdminToken(out.token);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  /** Ссылка восстановления пароля на админский адрес. */
  async function submitForgot(e: React.FormEvent) {
    e.preventDefault();
    const mail = email.trim();
    if (!mail) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const out = await apiPost<{ sent: boolean; smtp_configured: boolean; detail: string }>(
        "/api/v1/admin/auth/forgot",
        { email: mail },
      );
      setMessage(out.detail || "Проверьте почту.");
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md py-10">
      <h2 className="text-xl font-bold">Вход в админ-панель</h2>
      <p className="mt-1 text-sm text-text-secondary">
        {mode === "forgot"
          ? "Укажите админский email — пришлём ссылку для смены пароля."
          : mode === "token"
            ? "Резервный вход: admin-токен (выдаётся на сервере)."
            : "Войдите по админскому email и паролю."}
      </p>

      {mode === "forgot" ? (
        <form onSubmit={submitForgot} className="mt-5 flex flex-col gap-3">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Админский email"
            autoFocus
            className={INPUT_CLASS}
          />
          <button type="submit" disabled={busy || !email.trim()} className="btn-primary">
            {busy ? "Отправляем…" : "Прислать ссылку"}
          </button>
          {message ? <p className="text-sm text-accent-secondary">{message}</p> : null}
          {error ? <p className="text-sm text-accent-danger">{error}</p> : null}
          <button
            type="button"
            onClick={() => switchMode("password")}
            className="text-xs text-text-secondary transition-colors hover:text-text-primary"
          >
            ← назад ко входу
          </button>
        </form>
      ) : mode === "token" ? (
        <form onSubmit={submitToken} className="mt-5 flex flex-col gap-3">
          <input
            type="password"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="Admin-токен"
            autoFocus
            className={INPUT_CLASS}
          />
          <button type="submit" disabled={!tokenInput.trim()} className="btn-primary">
            Войти по токену
          </button>
          {error ? <p className="text-sm text-accent-danger">{error}</p> : null}
          <button
            type="button"
            onClick={() => switchMode("password")}
            className="text-xs text-text-secondary transition-colors hover:text-text-primary"
          >
            ← вход по email и паролю
          </button>
        </form>
      ) : (
        <form onSubmit={submitPassword} className="mt-5 flex flex-col gap-3">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Админский email"
            autoFocus
            className={INPUT_CLASS}
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Пароль"
            className={INPUT_CLASS}
          />
          <button type="submit" disabled={busy || !email.trim() || !password} className="btn-primary">
            {busy ? "Проверяем…" : "Войти"}
          </button>
          {error ? <p className="text-sm text-accent-danger">{error}</p> : null}
          <div className="flex items-center justify-between text-xs">
            <button
              type="button"
              onClick={() => switchMode("forgot")}
              className="text-text-secondary transition-colors hover:text-text-primary"
            >
              Забыли пароль?
            </button>
            <button
              type="button"
              onClick={() => switchMode("token")}
              className="text-text-muted transition-colors hover:text-text-primary"
            >
              вход по токену
            </button>
          </div>
        </form>
      )}

      <p className="mt-6 text-xs text-text-muted">
        Это служебный раздел сайта —{" "}
        <Link href="/" className="text-accent-primary hover:underline">
          на главную
        </Link>
      </p>
    </div>
  );
}
