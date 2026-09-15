import type { Metadata } from "next";

import TelegramExtras from "@/components/admin/TelegramExtras";
import TelegramPanel from "@/components/admin/TelegramPanel";

export const metadata: Metadata = { title: "Telegram-канал" };

/** Менеджер канала: композер, расписание, автопостинг с карантином и розыгрыши. */
export default function AdminTelegramPage() {
  return (
    <div>
      <h2 className="text-xl font-bold">Telegram-канал</h2>
      <p className="mt-0.5 mb-4 text-xs text-text-secondary">
        Канал — витрина закрытого архива: пост ведёт в бота, картинка собирается из
        превью и размывается. Выберите до четырёх файлов (или подставьте дайджест за
        сутки/неделю), проверьте предпросмотр и опубликуйте сразу либо поставьте в
        очередь на конкретное время. Автопост приходит вам в ЛС бота на подтверждение,
        а розыгрыши премиума бот ведёт вместе с каналом.
      </p>
      <TelegramPanel />
      <TelegramExtras />
    </div>
  );
}
