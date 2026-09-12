import type { Metadata } from "next";

/** Вход — служебная страница: robots.txt её закрывает, meta дублирует запрет. */
export const metadata: Metadata = {
  title: "Вход",
  robots: { index: false, follow: false },
};

export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return children;
}
