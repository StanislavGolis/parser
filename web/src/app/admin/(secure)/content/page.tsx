import type { Metadata } from "next";

import AdminConsole from "@/components/AdminConsole";

export const metadata: Metadata = { title: "Контент" };

/** Центр управления контентом: разделы, треды, хранилище, парсер. */
export default function AdminContentPage() {
  return <AdminConsole />;
}
