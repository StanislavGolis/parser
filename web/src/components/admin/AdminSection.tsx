"use client";

import { useEffect, useState, type ReactNode } from "react";

/**
 * Раздел админки с внутренними табами.
 *
 * Меню админки разрослось до девяти пунктов, часть из которых про одно и то же
 * («Обзор»/«Статистика»/«Пользователи», «Контент»/«Источники», «Жалобы»/«Обратная
 * связь»). Теперь меню — пять разделов, а близкие страницы живут табами внутри:
 * панель липкая, монтируется только активный таб (лишние запросы не уходят).
 *
 * Активный таб берётся из `?tab=…` (так работают старые адреса-редиректы и закладки),
 * а при переключении запоминается в `localStorage` — вернувшись в раздел, попадаешь
 * туда же, где закончил.
 */

export interface AdminSectionTab {
  value: string;
  label: string;
  /** Подсказка при наведении: что внутри таба. */
  hint?: string;
  /** Ленивый рендер: содержимое создаётся только для активного таба. */
  render: () => ReactNode;
}

interface Props {
  /** Ключ запоминания выбранного таба (у каждого раздела свой). */
  storageKey: string;
  /** Таб по умолчанию, если в адресе нет `?tab=`. */
  fallback: string;
  tabs: AdminSectionTab[];
}

export default function AdminSection({ storageKey, fallback, tabs }: Props) {
  const [tab, setTab] = useState(fallback);

  // Стартовый таб: сперва из адреса (старые ссылки и редиректы), затем из памяти
  useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("tab");
    if (fromUrl && tabs.some((item) => item.value === fromUrl)) {
      setTab(fromUrl);
      return;
    }
    const saved = window.localStorage.getItem(storageKey);
    if (saved && tabs.some((item) => item.value === saved)) setTab(saved);
  }, [storageKey, tabs]);

  function pick(value: string) {
    setTab(value);
    window.localStorage.setItem(storageKey, value);
    // Адрес обновляем без перехода: ссылку можно скопировать, история не засоряется
    const url = new URL(window.location.href);
    url.searchParams.set("tab", value);
    window.history.replaceState(null, "", url.toString());
  }

  const active = tabs.find((item) => item.value === tab) ?? tabs[0];

  return (
    <div>
      <div className="sticky top-0 z-10 mb-3 flex flex-wrap gap-1 border-b border-line bg-ink-primary py-2">
        {tabs.map((item) => {
          const isActive = item.value === active.value;
          return (
            <button
              key={item.value}
              type="button"
              onClick={() => pick(item.value)}
              title={item.hint}
              aria-current={isActive ? "page" : undefined}
              className={`rounded border px-2.5 py-1 text-xs transition-colors ${
                isActive
                  ? "border-accent-primary bg-accent-primary/10 text-accent-primary"
                  : "border-line text-text-secondary hover:text-text-primary"
              }`}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      {active.render()}
    </div>
  );
}
