import type { Metadata } from "next";

import AdminConsole from "@/components/AdminConsole";

export const metadata: Metadata = {
  title: "Админ-панель",
  robots: { index: false, follow: false },
};

export default function AdminPage() {
  return (
    <div className="container-site max-w-6xl py-6 sm:py-8">
      <AdminConsole />
    </div>
  );
}
