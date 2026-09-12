import { redirect } from "next/navigation";

/** Старые ссылки на «избранное»: избранное объединено с метками → /marks. */
export default function FavoritesRedirect() {
  redirect("/marks");
}
