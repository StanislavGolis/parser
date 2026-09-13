import type { Metadata } from "next";

import AdminOverviewPanel from "@/components/admin/AdminOverviewPanel";

export const metadata: Metadata = { title: "Обзор" };

export default function AdminHomePage() {
  return <AdminOverviewPanel />;
}
