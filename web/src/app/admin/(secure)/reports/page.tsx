import { redirect } from "next/navigation";

/** Старый адрес: жалобы — таб раздела «Обращения». */
export default function AdminReportsPage() {
  redirect("/admin/inbox?tab=reports");
}
