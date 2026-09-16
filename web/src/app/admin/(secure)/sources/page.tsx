import { redirect } from "next/navigation";

/** Старый адрес: источники — таб раздела «Контент». */
export default function AdminSourcesPage() {
  redirect("/admin/content?tab=sources");
}
