import { redirect } from "next/navigation";

/** Старый адрес: статистика — таб раздела «Обзор». */
export default function AdminStatsPage() {
  redirect("/admin?tab=stats");
}
