import { redirect } from "next/navigation";

/** Старый адрес: обратная связь — таб раздела «Обращения». */
export default function AdminFeedbackPage() {
  redirect("/admin/inbox?tab=feedback");
}
