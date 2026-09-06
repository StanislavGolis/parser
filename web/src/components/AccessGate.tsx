"use client";

import { useState } from "react";

import { LockIcon, SpinnerIcon } from "@/components/icons";
import { apiPost } from "@/lib/api";
import type { AccessResult } from "@/lib/types";

/**
 * Форма ввода кода доступа к приватному разделу.
 * При успехе API выставляет httpOnly-cookie (24 ч), страница перезагружается.
 */
export default function AccessGate({
  slug,
  title,
  description,
}: {
  slug: string;
  title?: string;
  description?: string | null;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await apiPost<AccessResult>(`/api/v1/boards/${encodeURIComponent(slug)}/access`, { code });
      window.location.reload();
    } catch (err) {
      setError("Неверный код доступа. Проверьте и попробуйте ещё раз.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-8 flex w-full max-w-md flex-col items-center gap-4 rounded border border-line bg-ink-secondary px-6 py-12 text-center">
      <span className="flex h-10 w-10 items-center justify-center rounded border border-accent-warning/40 text-accent-warning">
        <LockIcon className="h-5 w-5" />
      </span>

      <div>
        <h2 className="font-mono text-sm font-bold uppercase tracking-[0.12em] text-text-primary">
          приватная доска
        </h2>
        <p className="mt-1 font-mono text-[11px] text-text-muted">
          /{slug}
          {title ? ` — ${title}` : ""}
        </p>
        {description ? (
          <p className="mt-2 text-sm text-text-secondary">{description}</p>
        ) : null}
        <p className="mt-3 text-sm text-text-secondary">
          Для доступа введите код. Доступ сохранится на 24 часа.
        </p>
      </div>

      <form onSubmit={submit} className="flex w-full flex-col gap-3">
        <input
          type="password"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Код доступа"
          autoFocus
          className="input-sluice w-full"
        />
        <button type="submit" disabled={busy || !code.trim()} className="btn-primary">
          {busy ? <SpinnerIcon className="h-4 w-4" /> : <LockIcon className="h-4 w-4" />}
          Войти
        </button>
      </form>
      {error ? <p className="text-sm text-accent-danger">{error}</p> : null}
    </div>
  );
}
