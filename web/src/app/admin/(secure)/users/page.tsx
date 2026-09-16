import { redirect } from "next/navigation";

/** Старый адрес: пользователи — таб раздела «Обзор». */
export default function AdminUsersPage() {
  redirect("/admin?tab=users");
}
