import type { Metadata } from "next";

import AdminSection from "@/components/admin/AdminSection";
import FeedbackPanel from "@/components/admin/FeedbackPanel";
import ReportsPanel from "@/components/admin/ReportsPanel";

export const metadata: Metadata = { title: "Обращения" };

/**
 * Обращения — раздел из двух табов: жалобы на файлы и приёмная обратной связи.
 *
 * Оба таба про «что пишут люди», поэтому раньше стояли в меню рядом и мешали
 * остальным пунктам. Старые адреса `/admin/reports` и `/admin/feedback` редиректят сюда.
 */
export default function AdminInboxPage() {
  return (
    <div>
      <h2 className="text-xl font-bold">Обращения</h2>
      <p className="mt-0.5 mb-4 text-xs text-text-secondary">
        Всё, что пишут люди: жалобы на файлы (модерация и блок-лист) и обращения через
        форму — подписка, баги, идеи, контент.
      </p>
      <AdminSection
        storageKey="admin-inbox-tab"
        fallback="reports"
        tabs={[
          {
            value: "reports",
            label: "Жалобы",
            hint: "Очередь жалоб: скрыть файл, тред, удалить; блок-лист хешей",
            content: <ReportsPanel />,
          },
          {
            value: "feedback",
            label: "Обратная связь",
            hint: "Форма с сайта: статусы и заметки-ответы",
            content: <FeedbackPanel />,
          },
        ]}
      />
    </div>
  );
}
