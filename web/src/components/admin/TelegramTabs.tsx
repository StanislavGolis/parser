"use client";

import { useEffect, useState } from "react";

import TelegramExtras from "@/components/admin/TelegramExtras";
import TelegramPanel from "@/components/admin/TelegramPanel";

/**
 * Вкладки внутри раздела «Канал».
 *
 * Раньше всё шло одним потоком — композер, журнал публикаций, автопостинг и
 * розыгрыши, около тысячи строк в столбик: чтобы дойти до розыгрышей, приходилось
 * долго скроллить. Теперь это четыре короткие вкладки, и каждая грузит только свои
 * данные (панели монтируются по одной).
 */

type Tab = "composer" | "log" | "autopost" | "giveaways";

const TABS: Array<{ value: Tab; label: string; hint: string }> = [
  { value: "composer", label: "Пост", hint: "Собрать и опубликовать пост в канал" },
  { value: "log", label: "Журнал", hint: "Что и когда публиковалось" },
  { value: "autopost", label: "Автопостинг", hint: "Расписание, карантин, окна тишины" },
  { value: "giveaways", label: "Розыгрыши", hint: "Конкурсы премиум-подписки" },
];

const STORAGE_KEY = "admin-telegram-tab";

export default function TelegramTabs() {
  const [tab, setTab] = useState<Tab>("composer");

  // Возвращаемся на ту вкладку, где админ работал в прошлый раз
  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved && TABS.some((item) => item.value === saved)) setTab(saved as Tab);
  }, []);

  function pick(value: Tab) {
    setTab(value);
    window.localStorage.setItem(STORAGE_KEY, value);
  }

  return (
    <div>
      {/* Панель вкладок липкая: переключиться можно с любого места длинного журнала */}
      <div className="sticky top-0 z-10 mb-3 flex flex-wrap gap-1 border-b border-line bg-ink-primary py-2">
        {TABS.map((item) => {
          const active = tab === item.value;
          return (
            <button
              key={item.value}
              type="button"
              onClick={() => pick(item.value)}
              title={item.hint}
              aria-current={active ? "page" : undefined}
              className={`rounded border px-2.5 py-1 text-xs transition-colors ${
                active
                  ? "border-accent-primary bg-accent-primary/10 text-accent-primary"
                  : "border-line text-text-secondary hover:text-text-primary"
              }`}
            >
              {item.label}
            </button>
          );
        })}
      </div>

      {tab === "composer" ? <TelegramPanel section="composer" /> : null}
      {tab === "log" ? <TelegramPanel section="log" /> : null}
      {tab === "autopost" ? <TelegramExtras section="autopost" /> : null}
      {tab === "giveaways" ? <TelegramExtras section="giveaways" /> : null}
    </div>
  );
}
