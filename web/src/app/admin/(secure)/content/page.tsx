import type { Metadata } from "next";

import AdminSection from "@/components/admin/AdminSection";
import AdminConsole from "@/components/AdminConsole";
import SourcesPanel from "@/components/admin/SourcesPanel";

export const metadata: Metadata = { title: "Контент" };

/**
 * Контент — раздел из двух табов: консоль (разделы, треды, хранилище) и реестр
 * источников парсинга. Раньше «Контент» и «Источники» были отдельными вкладками
 * меню, хотя описывают одно поле — откуда и что мы берём.
 */
export default function AdminContentPage() {
  return (
    <div>
      <h2 className="text-xl font-bold">Контент</h2>
      <p className="mt-0.5 mb-4 text-xs text-text-secondary">
        Разделы, треды, хранилище и парсер — и рядом реестр источников: прогоны,
        расписание, лимиты и история.
      </p>
      <AdminSection
        storageKey="admin-content-tab"
        fallback="boards"
        tabs={[
          {
            value: "boards",
            label: "Разделы и треды",
            hint: "Консоль: разделы, треды, кэш медиа, операции с S3",
            content: <AdminConsole />,
          },
          {
            value: "sources",
            label: "Источники",
            hint: "Реестр парсеров: запуск, расписание, лимиты, журнал прогонов",
            content: <SourcesPanel />,
          },
        ]}
      />
    </div>
  );
}

