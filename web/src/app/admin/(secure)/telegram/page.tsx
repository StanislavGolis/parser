import type { Metadata } from "next";

import TelegramTabs from "@/components/admin/TelegramTabs";

export const metadata: Metadata = { title: "Telegram-канал" };

/** Менеджер канала: вкладки «Пост», «Журнал», «Автопостинг», «Розыгрыши». */
export default function AdminTelegramPage() {
  return (
    <div>
      <h2 className="text-xl font-bold">Telegram-канал</h2>
      <p className="mt-0.5 mb-4 text-xs text-text-secondary">
        Пост ведёт в бота, картинка собирается из превью и размывается. Автопост приходит
        вам в ЛС бота на подтверждение, розыгрыши бот ведёт вместе с каналом.
      </p>
      <TelegramTabs />
    </div>
  );
}
