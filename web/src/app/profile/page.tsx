"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { LockIcon, SpinnerIcon, StarIcon, TagIcon } from "@/components/icons";
import { ApiError, apiSend } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import type { UserOut } from "@/lib/types";

function formatUntil(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("ru-RU");
}

/** Профиль пользователя: премиум-статус и промо-активация подписки. */
export default function ProfilePage() {
  const router = useRouter();
  const [user, setUser] = useState<UserOut | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setUser(await apiSend<UserOut>("/api/v1/auth/me"));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError("Не удалось загрузить профиль.");
    } finally {
      setReady(true);
    }
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  async function activate() {
    setBusy(true);
    setError(null);
    try {
      setUser(await apiSend<UserOut>("/api/v1/auth/premium/activate", { method: "POST" }));
      // Перерисовываем SSR-данные: превью премиум-файлов должны перестать блюриться
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? (err.detail ?? err.message) : "Не удалось активировать премиум.");
    } finally {
      setBusy(false);
    }
  }

  if (!ready) {
    return (
      <div className="container-site max-w-md py-10">
        <p className="font-mono text-xs text-text-muted">Загружаем профиль…</p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="container-site max-w-md py-10">
        <p className="text-sm text-text-secondary">{error ?? "Требуется вход."}</p>
      </div>
    );
  }

  return (
    <div className="container-site max-w-md py-10">
      <h1 className="text-xl font-bold text-text-primary">Профиль</h1>
      <p className="mt-1 font-mono text-[11px] text-text-muted">{user.email}</p>

      <div
        className={`mt-6 rounded border px-4 py-4 ${
          user.is_premium ? "border-accent-warning/40 bg-accent-warning/5" : "border-line bg-ink-secondary"
        }`}
      >
        <div className="flex items-center gap-2">
          {user.is_premium ? (
            <StarIcon className="h-4 w-4 text-accent-warning" />
          ) : (
            <LockIcon className="h-4 w-4 text-text-muted" />
          )}
          <span className="font-mono text-xs uppercase tracking-widest text-text-primary">
            {user.is_premium ? "премиум активен" : "бесплатный доступ"}
          </span>
        </div>

        <p className="mt-2 text-sm text-text-secondary">
          {user.is_premium
            ? "Доступны премиум-разделы, скачивание и оригиналы файлов."
            : "Метки уже доступны. Премиум добавляет премиум-разделы, скачивание и оригиналы файлов."}
        </p>

        <p className="mt-2 font-mono text-[11px] text-text-muted">
          Действует до: {formatUntil(user.premium_until)}
        </p>

        <button type="button" onClick={() => void activate()} disabled={busy} className="btn-primary mt-4 w-full">
          {busy ? <SpinnerIcon className="h-4 w-4" /> : null}
          {busy
            ? "Активируем…"
            : user.is_premium
              ? "Продлить премиум на 1 день"
              : "Активировать премиум на 1 день"}
        </button>
        <p className="mt-2 text-[11px] text-text-muted">
          Пока бесплатно (тестовый период). Повторная активация продлевает срок.
        </p>
      </div>

      {error ? <p className="mt-4 text-sm text-accent-danger">{error}</p> : null}

      {/* Активность пользователя: метки (личный список — на /marks) */}
      <Link
        href="/marks"
        className="mt-4 block rounded border border-line bg-ink-secondary px-4 py-3 transition-colors hover:border-accent-primary"
        title="Открыть мои метки"
      >
        <span className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-text-muted">
          <TagIcon className="h-4 w-4" />
          мои метки
        </span>
        <span className="mt-1 block font-mono text-lg text-text-primary">
          {formatNumber(user.marks_count ?? 0)}
        </span>
      </Link>

      <p className="mt-4 text-[11px] leading-relaxed text-text-muted">
        Метка «отличный контент» — наш аналог лайка: она поднимает файл в сортировке «по меткам»,
        влияет на «Популярное» и собирает ваш личный список на странице «Метки».
      </p>

      <p className="mt-6 text-xs text-text-muted">
        <Link href="/" className="hover:text-text-secondary">
          ← На главную
        </Link>
      </p>
    </div>
  );
}
