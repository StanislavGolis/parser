import type { Metadata } from "next";

import AdminSection from "@/components/admin/AdminSection";
import PlansPanel from "@/components/admin/PlansPanel";

export const metadata: Metadata = { title: "Продажи" };

/**
 * Тарифы подписки: цены и сроки, стартовая акция и журнал оплат.
 *
 * Модель «открытый архив»: Free видит открытые разделы (с рекламой), Premium открывает
 * приватные разделы, скачивание и убирает рекламу. Здесь всё, что раньше требовало
 * деплоя: цена, срок, включение тарифа и условия акции.
 */
export default function AdminPlansPage() {
  return (
    <div>
      <h2 className="text-xl font-bold">Продажи</h2>
      <p className="mt-0.5 mb-4 text-xs text-text-secondary">
        Тарифы, акции и цены — в звёздах Telegram и в USDT для крипты; рядом балансы
        кошельков и журнал оплат. Рублёвая цена хранится справочно.
      </p>
      <AdminSection
        storageKey="admin-plans-tab"
        fallback="plans"
        tabs={[
          {
            value: "plans",
            label: "Тарифы и акции",
            hint: "Цены в звёздах и USDT, сроки, включение тарифов, акции",
            content: <PlansPanel section="plans" />,
          },
          {
            value: "wallet",
            label: "Кошельки и журнал",
            hint: "Балансы звёзд и крипты, ручная выдача, история оплат",
            content: <PlansPanel section="wallet" />,
          },
        ]}
      />
    </div>
  );
}