"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Предупреждение о контенте 18+.
 *
 * Показываем один раз в сутки: факт подтверждения лежит в cookie `dv_age`
 * (`max-age=86400`, path=/), поэтому повторный заход в тот же день окно не
 * показывает. Кука — первое лицо: сервер её не читает, разметка страниц не
 * зависит от ответа (контент остаётся доступен поисковикам и при JS-off.
 */

const COOKIE = "dv_age";
const TTL_SECONDS = 24 * 60 * 60; // сутки — «раз в день»
const EXIT_URL = "https://www.google.com/";

function hasConsent(): boolean {
  return document.cookie
    .split("; ")
    .some((part) => part.startsWith(`${COOKIE}=ok`));
}

function rememberConsent(): void {
  document.cookie = `${COOKIE}=ok; path=/; max-age=${TTL_SECONDS}; samesite=lax`;
}

export default function AgeGate() {
  const [open, setOpen] = useState(false);
  const [denied, setDenied] = useState(false);

  useEffect(() => {
    if (!hasConsent()) setOpen(true);
  }, []);

  const confirm = useCallback(() => {
    rememberConsent();
    setOpen(false);
  }, []);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="age-gate-title"
      className="fixed inset-0 z-[100] flex items-center justify-center bg-ink-primary/95 px-4 backdrop-blur-sm"
    >
      <div className="w-full max-w-md rounded border border-line bg-ink-secondary p-5 shadow-lg">
        <h2
          id="age-gate-title"
          className="font-mono text-sm font-bold uppercase tracking-[0.08em] text-text-primary"
        >
          18+ · только для взрослых
        </h2>

        <p className="mt-3 text-sm leading-relaxed text-text-secondary">
          На сайте публикуются материалы для взрослых. Продолжая, вы подтверждаете,
          что вам 18 лет или больше и просмотр такого контента законен в вашей стране.
        </p>
        <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
          Подтверждение хранится в cookie один сутки. Мы не показываем это
          предупреждение чаще и не собираем персональные данные для проверки возраста.
        </p>

        {denied ? (
          <div className="mt-4 rounded border border-accent-danger/30 bg-red-500/10 px-3 py-2.5">
            <p className="text-sm text-accent-danger">
              Доступ закрыт: материалы сайта не предназначены для несовершеннолетних.
            </p>
            <a
              href={EXIT_URL}
              rel="noreferrer"
              className="mt-2 inline-block text-xs text-text-secondary underline transition-colors hover:text-text-primary"
            >
              Покинуть сайт →
            </a>
          </div>
        ) : null}

        <div className="mt-5 flex flex-wrap gap-2">
          <button type="button" onClick={confirm} className="btn-primary px-4 py-2 text-xs">
            Мне 18 или больше — войти
          </button>
          <button
            type="button"
            onClick={() => setDenied(true)}
            className="btn-ghost px-4 py-2 text-xs"
          >
            Мне меньше 18
          </button>
        </div>
      </div>
    </div>
  );
}
