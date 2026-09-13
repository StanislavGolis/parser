"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

/**
 * Онбординг новичка: одна короткая модалка при первом визите.
 *
 * Зачем: с витрины не видно, что такое закладка, зачем аккаунт и чем премиум
 * отличается от бесплатного доступа. Показываем один раз (cookie `dv_onboard`),
 * после подтверждения 18+ — иначе две модалки накладывались бы друг на друга.
 * Поисковым роботам окно не отдаётся: см. `layout.tsx`.
 */

const COOKIE = "dv_onboard";
const AGE_COOKIE = "dv_age";
const TTL_SECONDS = 365 * 24 * 60 * 60;

function hasCookie(name: string): boolean {
  return document.cookie.split("; ").some((part) => part.startsWith(`${name}=`));
}

function rememberOnboarded(): void {
  document.cookie = `${COOKIE}=ok; path=/; max-age=${TTL_SECONDS}; samesite=lax`;
}

export default function Onboarding() {
  const [open, setOpen] = useState(false);
  const [details, setDetails] = useState(false);

  useEffect(() => {
    function maybeOpen() {
      // Уже видел — не мешаем. Возраст ещё не подтверждён — ждём AgeGate.
      if (hasCookie(COOKIE) || !hasCookie(AGE_COOKIE)) return;
      setOpen(true);
    }
    maybeOpen();
    // AgeGate сообщает о подтверждении — тогда показываем онбординг
    window.addEventListener("dredge:age-ok", maybeOpen);
    return () => window.removeEventListener("dredge:age-ok", maybeOpen);
  }, []);

  const close = useCallback(() => {
    rememberOnboarded();
    setOpen(false);
  }, []);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
      className="fixed inset-0 z-[95] flex items-center justify-center bg-ink-primary/90 px-4 backdrop-blur-sm"
    >
      <div className="w-full max-w-lg rounded border border-line bg-ink-secondary p-5 shadow-lg">
        <h2
          id="onboarding-title"
          className="font-mono text-sm font-bold uppercase tracking-[0.08em] text-text-primary"
        >
          dredger — автоматический медиа-архив
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-text-secondary">
          Смотри бесплатно, отмечай лучшее, скачивай нужное. Файлы собираются из
          архивов автоматически и обновляются каждый день.
        </p>

        {details ? (
          <ul className="mt-4 space-y-2.5 text-sm text-text-secondary">
            <li className="rounded border border-line bg-ink-primary/40 px-3 py-2">
              <span className="font-mono text-[11px] uppercase tracking-wider text-accent-primary">
                закладка
              </span>
              <p className="mt-1 text-[13px] leading-relaxed">
                Личный список лучшего: нажмите 🔖 на карточке или пробел в просмотре —
                файл появится на странице <span className="text-text-primary">«Закладки»</span>.
                Нужен аккаунт.
              </p>
            </li>
            <li className="rounded border border-line bg-ink-primary/40 px-3 py-2">
              <span className="font-mono text-[11px] uppercase tracking-wider text-accent-primary">
                аккаунт
              </span>
              <p className="mt-1 text-[13px] leading-relaxed">
                Бесплатно: закладки, свои настройки лент и продолжение просмотра на любом
                устройстве. Регистрация занимает минуту.
              </p>
            </li>
            <li className="rounded border border-line bg-ink-primary/40 px-3 py-2">
              <span className="font-mono text-[11px] uppercase tracking-wider text-accent-warning">
                премиум
              </span>
              <p className="mt-1 text-[13px] leading-relaxed">
                Закрытые разделы, скачивание файлов и оригиналы. Выдаётся вручную по заявке
                в профиле — стоимость и срок видно там же.
              </p>
            </li>
          </ul>
        ) : null}

        <div className="mt-5 flex flex-wrap gap-2">
          <button type="button" onClick={close} className="btn-primary px-4 py-2 text-xs">
            Понятно
          </button>
          {details ? (
            <Link href="/boards" className="btn-ghost px-4 py-2 text-xs">
              К разделам архива →
            </Link>
          ) : (
            <button
              type="button"
              onClick={() => setDetails(true)}
              className="btn-ghost px-4 py-2 text-xs"
            >
              Подробнее
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
