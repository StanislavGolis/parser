import type { Metadata } from "next";

import SourcesPanel from "@/components/admin/SourcesPanel";

export const metadata: Metadata = { title: "Источники" };

/** Реестр источников контента: прогоны, расписание, лимиты, журнал. */
export default function AdminSourcesPage() {
  return (
    <div>
      <h2 className="text-xl font-bold">Источники контента</h2>
      <p className="mt-0.5 mb-4 text-xs text-text-secondary">
        Реестр источников парсинга: 2ch.hk и сайты-источники. У каждого свой
        контейнер-прогон, свой флаг запуска и своя история; добавить источник —
        значит завести адаптер и запись здесь.
      </p>
      <SourcesPanel />
    </div>
  );
}
