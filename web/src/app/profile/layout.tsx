import type { Metadata } from "next";

/** Профиль доступен только своему владельцу — из индекса исключаем. */
export const metadata: Metadata = {
  title: "Профиль",
  robots: { index: false, follow: false },
};

export default function ProfileLayout({ children }: { children: React.ReactNode }) {
  return children;
}
