import type { Metadata } from "next";

/** Страница сброса пароля (ссылка из письма) — из индекса исключаем. */
export const metadata: Metadata = {
  title: "Сброс пароля",
  robots: { index: false, follow: false },
};

export default function ResetLayout({ children }: { children: React.ReactNode }) {
  return children;
}
