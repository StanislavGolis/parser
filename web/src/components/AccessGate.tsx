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
    <div className="flex flex-col items-center justify-center gap-4 rounded-2xl border border-dashed border-neutral-700 bg-neutral-900/40 px-6 py-16 text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-500/15 text-amber-300">
        <LockIcon className="h-7 w-7" />
      </span>
      <div>
        <h2 className="text-lg font-semibold text-neutral-100">
          {title ? `/${slug} — ${title}` : `/${slug}`} — закрытый раздел
        </h2>
        {description ? <p className="mt-1 text-sm text-neutral-400">{description}</p> : null}
        <p className="mt-1 text-sm text-neutral-500">
          Раздел доступен только по коду. Введите код, чтобы открыть контент.
        </p>
      </div>

      <form onSubmit={submit} className="flex w-full max-w-sm flex-col gap-3 sm:flex-row">
        <input
          type="password"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Код доступа"
          autoFocus
          className="flex-1 rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 outline-none transition-colors placeholder:text-neutral-600 focus:border-amber-500"
        />
        <button type="submit" disabled={busy || !code.trim()} className="btn-primary">
          {busy ? <SpinnerIcon className="h-4 w-4" /> : <LockIcon className="h-4 w-4" />}
          Открыть
        </button>
      </form>
      {error ? <p className="text-sm text-red-400">{error}</p> : null}
    </div>
  );
}
