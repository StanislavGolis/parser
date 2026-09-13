"use client";

import AdminLogin from "@/components/admin/AdminLogin";
import AdminNav from "@/components/admin/AdminNav";
import { useAdminToken } from "@/lib/adminAuth";

/**
 * Оболочка админки: гейт по admin-токену + навигация по вкладкам.
 *
 * Лежит в route-group `(secure)`, чтобы служебная страница сброса пароля
 * `/admin/reset` (её открывают по ссылке из письма, без токена) осталась
 * вне гейта.
 */
export default function AdminPanelLayout({ children }: { children: React.ReactNode }) {
  const { token, ready, logout } = useAdminToken();

  // Токен читается в эффекте — до этого показываем нейтральную строку,
  // чтобы не мигала форма входа при живом токене.
  if (!ready) {
    return (
      <div className="container-site max-w-6xl py-10">
        <p className="font-mono text-xs text-text-muted">проверяем доступ…</p>
      </div>
    );
  }

  if (!token) {
    return (
      <div className="container-site max-w-6xl py-6 sm:py-8">
        <AdminLogin />
      </div>
    );
  }

  return (
    <div className="container-site max-w-6xl py-6 sm:py-8">
      <AdminNav onLogout={logout} />
      {children}
    </div>
  );
}
