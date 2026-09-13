import type { Metadata } from "next";

import FeedbackPanel from "@/components/admin/FeedbackPanel";

export const metadata: Metadata = { title: "Обратная связь" };

/** Приёмная обратной связи: заявки посетителей, статусы и заметки-ответы. */
export default function AdminFeedbackPage() {
  return (
    <div>
      <h2 className="text-xl font-bold">Обратная связь</h2>
      <p className="mt-0.5 mb-4 text-xs text-text-secondary">
        Заявки с сайта: баги, идеи, запросы премиум-доступа. Каждое обращение приходит
        письмом админам; статусы (новое → в работе → отвечено → закрыто) и заметки
        видны здесь.
      </p>
      <FeedbackPanel />
    </div>
  );
}
