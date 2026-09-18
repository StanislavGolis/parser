"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, apiSend } from "@/lib/api";
import { notifyAuthChanged } from "@/lib/authEvents";
import { TELEGRAM_BOT_USERNAME } from "@/lib/env";
import type { UserOut } from "@/lib/types";

/**
 * Вход на сайт.
 *
 * Модель Dredger 2.0: вход один — через Telegram-бота, он же проверяет подписку
 * и присылает одноразовую ссылку. Форма email/пароля осталась только для админов
 * и VIP: она спрятана за маленькой ссылкой, чтобы не отвлекать посетителя.
 */
export default function LoginPage() {
  const router = useRouter();
  const [showAdmin, setShowAdmin] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Сообщение о неудачном входе по ссылке из бота: `/auth/magic` уводит сюда с
  // `?error=magic|api` — раньше этот параметр никак не показывался, и человек
  // видел ту же форму входа без объяснения, что ссылка уже не работает.
  const [linkError, setLinkError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get("error");
    if (code === "magic") {
      setLinkError(
        "Ссылка для входа уже использована или истекла. Нажмите «Войти через Telegram» — бот пришлёт новую.",
      );
    } else if (code === "api") {
      setLinkError("Сервис входа не ответил. Попробуйте ещё раз через минуту.");
    }
  }, []);

  /** Возврат туда, куда шёл пользователь: middleware добавляет `?next=/board/...`. */
  function goNext() {
    const next = new URLSearchParams(window.location.search).get("next");
    router.push(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiSend<UserOut>("/api/v1/auth/login", {
        method: "POST",
        body: { email, password },
      });
      // Шапка — клиентский компонент с собственным состоянием: сообщаем ей о входе,
      // иначе имя профиля появилось бы только после перезагрузки.
      notifyAuthChanged();
      router.refresh();
      goNext();
    } catch (err) {
      setError(err instanceof ApiError ? (err.detail ?? err.message) : "Ошибка входа");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="container-site max-w-md py-10">
      <h1 className="text-xl font-bold text-text-primary">Вход</h1>
      <p className="mt-1 text-sm text-text-secondary">
        Доступ к архиву — по одноразовой ссылке из Telegram-бота.
      </p>

      <div className="mt-6 rounded border border-line bg-ink-secondary p-4">
        {linkError ? (
          <p className="mb-3 rounded border border-accent-warning/40 bg-accent-warning/10 px-3 py-2 text-xs text-accent-warning">
            {linkError}
          </p>
        ) : null}
        {TELEGRAM_BOT_USERNAME ? (
          <a
            href={`https://t.me/${TELEGRAM_BOT_USERNAME}?start=site`}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-primary block text-center"
          >
            Войти через Telegram
          </a>
        ) : (
          <p className="text-xs text-text-muted">
            Ник бота не задан в сборке — вход временно недоступен, напишите администратору.
          </p>
        )}
        <p className="mt-2 text-[11px] text-text-muted">
          Ссылка действует 10 минут. Подписка для входа не нужна.
        </p>
      </div>

      {/* Админский вход: спрятан, чтобы не отвлекать обычных посетителей */}
      {showAdmin ? (
        <form onSubmit={submit} className="mt-6 flex flex-col gap-3">
          <p className="text-xs text-text-muted">
            Вход по email и паролю — для админов и VIP-аккаунтов.
          </p>
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
              autoComplete="current-password"
            />
          </label>

          {error ? <p className="text-sm text-accent-danger">{error}</p> : null}

          <button type="submit" disabled={busy} className="btn-primary mt-1">
            {busy ? "Подождите…" : "Войти"}
          </button>
          <button
            type="button"
            onClick={() => {
              setShowAdmin(false);
              setError(null);
            }}
            className="text-left text-xs text-text-muted hover:text-text-secondary"
          >
            ← Обычный вход через Telegram
          </button>
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setShowAdmin(true)}
          className="mt-4 text-xs text-text-muted underline-offset-2 hover:text-text-secondary hover:underline"
        >
          Вход для админов
        </button>
      )}

      <p className="mt-8 text-xs text-text-muted">
        <Link href="/" className="hover:text-text-secondary">
          ← На главную
        </Link>
      </p>
    </div>
  );
}
