import type { Metadata } from "next";

import ReportsPanel from "@/components/admin/ReportsPanel";

export const metadata: Metadata = { title: "Жалобы" };

/** Модерация: очередь жалоб на файлы и блок-лист запрещённых хешей. */
export default function AdminReportsPage() {
  return (
    <div>
      <h2 className="text-xl font-bold">Жалобы</h2>
      <p className="mt-0.5 mb-4 text-xs text-text-secondary">
        Жалобы с сайта (кнопка «Пожаловаться» в лайтбоксе и на странице файла): скрыть
        файл, скрыть тред, удалить файл вместе с объектами в хранилище или отклонить.
        Жалобы про детскую безопасность закрывают доступ автоматически, ещё до разбора,
        а их хеши уходят в блок-лист.
      </p>
      <ReportsPanel />
    </div>
  );
}
