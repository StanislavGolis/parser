import type { Metadata } from "next";

import AdminSection from "@/components/admin/AdminSection";
import AdminOverviewPanel from "@/components/admin/AdminOverviewPanel";
import AdminStatsPanel from "@/components/admin/AdminStatsPanel";
import AdminUsersPanel from "@/components/admin/AdminUsersPanel";

export const metadata: Metadata = { title: "Обзор" };

/**
 * Обзор — раздел из трёх табов: дашборд, статистика и пользователи.
 *
 * Раньше это были три отдельные вкладки меню, хотя отвечают на один вопрос
 * «что происходит». Старые адреса `/admin/stats` и `/admin/users` редиректят сюда.
 */
export default function AdminHomePage() {
  return (
    <div>
      <h2 className="text-xl font-bold">Обзор</h2>
      <p className="mt-0.5 mb-4 text-xs text-text-secondary">
        Что происходит сейчас: состояние парсера и объёмы архива, посещаемость и топы,
        аккаунты и подписки.
      </p>
      <AdminSection
        storageKey="admin-overview-tab"
        fallback="dashboard"
        tabs={[
          {
            value: "dashboard",
            label: "Дашборд",
            hint: "Состояние парсера, объёмы, кэш медиа",
            render: () => <AdminOverviewPanel />,
          },
          {
            value: "stats",
            label: "Статистика",
            hint: "Посещаемость, топы, отчёты за период",
            render: () => <AdminStatsPanel />,
          },
          {
            value: "users",
            label: "Пользователи",
            hint: "Аккаунты, подписки, сессии, ручная выдача",
            render: () => <AdminUsersPanel />,
          },
        ]}
      />
    </div>
  );
}

