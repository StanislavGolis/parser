"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { BookmarkIcon, LockIcon, StarIcon } from "@/components/icons";
import { ApiError, apiSend } from "@/lib/api";
import { notifyAuthChanged } from "@/lib/authEvents";
import { formatNumber, parseUtc } from "@/lib/format";
import type { UserOut } from "@/lib/types";

/** Дата из API (UTC) в местном времени — с корректным разбором без `Z`. */
function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const time = parseUtc(iso);
  if (!Number.isFinite(time)) return "—";
  return new Date(time).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "long",
    year: "numeric",
  });
}

/**
 * Профиль: статус доступа, метки и управление аккаунтом.
 *
 * Премиум здесь **не выдаётся**: доступ включает администратор вручную, а заявка
 * уходит через форму обратной связи (тема «Премиум-доступ») — так видно, кому и
 * когда доступен полный контент, и нет кнопки «выдать себе премиум».
 */
export default function ProfilePage() {
  const router = useRouter();
  const [user, setUser] = useState<UserOut | null>(null);
  const [ready, setReady] = useState(false);
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

  async function logout() {
    try {
      await apiSend("/api/v1/auth/logout", { method: "POST" });
    } catch {
      /* локальное состояние всё равно сбрасываем */
    }
    // Просим Next перерисовать серверные компоненты: иначе в шапке и на страницах
    // останутся данные вошедшего пользователя до ручной перезагрузки.
    notifyAuthChanged();
    router.refresh();
    router.push("/");
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
      <h1 className="dredge-title">профиль</h1>
      <p className="mt-2 font-mono text-[11px] text-text-muted">{user.email}</p>

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
            {user.is_premium ? "премиум активен" : "базовый доступ"}
          </span>
        </div>

        <p className="mt-2 text-sm text-text-secondary">
          {user.is_premium
            ? "Доступны премиум-разделы, скачивание и оригиналы файлов."
            : "Закладки и весь бесплатный контент доступны. Премиум добавляет закрытые разделы, скачивание и оригиналы."}
        </p>

        <p className="mt-2 font-mono text-[11px] text-text-muted">
          {user.is_premium
            ? `Действует до: ${formatDate(user.premium_until)}`
            : "Премиум выдаётся вручную — отправьте заявку."}
        </p>

        {user.is_premium ? null : (
          <Link href="/feedback?topic=premium" className="btn-primary mt-4 block w-full text-center">
            Запросить премиум-доступ
          </Link>
        )}
        <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
          Заявка уходит администратору вместе с вашим email — доступ включают вручную, статус и
          срок появятся здесь.
        </p>
      </div>

      {error ? <p className="mt-4 text-sm text-accent-danger">{error}</p> : null}

      {/* Закладки: личный список живёт на /marks */}
      <Link
        href="/marks"
        className="mt-4 block rounded border border-line bg-ink-secondary px-4 py-3 transition-colors hover:border-accent-primary"
        title="Открыть мои закладки"
      >
        <span className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-text-muted">
          <BookmarkIcon className="h-4 w-4" />
          мои закладки
        </span>
        <span className="mt-1 block font-mono text-lg text-text-primary">
          {formatNumber(user.marks_count ?? 0)}
        </span>
      </Link>

      <p className="mt-3 text-[11px] leading-relaxed text-text-muted">
        Закладка — личный список: отмеченный файл поднимается в «Популярном» и собирается
        на странице «Закладки».
      </p>

      {/* Аккаунт и связь */}
      <div className="mt-4 rounded border border-line bg-ink-secondary px-4 py-3">
        <dl className="flex flex-col gap-1.5 font-mono text-[11px] text-text-muted">
          <div className="flex justify-between gap-3">
            <dt>аккаунт</dt>
            <dd className="truncate text-text-secondary">{user.email}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt>с нами с</dt>
            <dd className="text-text-secondary">{formatDate(user.created_at)}</dd>
          </div>
        </dl>
        <div className="mt-3 flex flex-wrap gap-2">
          <Link href="/feedback" className="btn-ghost px-3 py-1.5 text-xs">
            Обратная связь
          </Link>
          <button type="button" onClick={() => void logout()} className="btn-ghost px-3 py-1.5 text-xs">
            Выйти
          </button>
        </div>
      </div>

      <p className="mt-6 text-xs text-text-muted">
        <Link href="/" className="hover:text-text-secondary">
          ← На главную
        </Link>
      </p>
    </div>
  );
}
