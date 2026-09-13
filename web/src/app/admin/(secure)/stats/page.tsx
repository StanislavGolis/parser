import type { Metadata } from "next";

import AdminStatsPanel from "@/components/admin/AdminStatsPanel";

export const metadata: Metadata = { title: "Статистика" };

export default function AdminStatsPage() {
  return <AdminStatsPanel />;
}
