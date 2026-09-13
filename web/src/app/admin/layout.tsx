import type { Metadata } from "next";

/** Админка целиком закрыта от индексации (плюс robots.txt). */
export const metadata: Metadata = {
  title: { default: "Админ-панель", template: "%s · DREDGER admin" },
  robots: { index: false, follow: false },
};

export default function AdminSectionLayout({ children }: { children: React.ReactNode }) {
  return children;
}
