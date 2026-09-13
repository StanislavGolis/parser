import type { Metadata } from "next";

/** Служебная страница (ссылка из письма): из индекса закрыта. */
export const metadata: Metadata = {
  title: "Смена пароля",
  robots: { index: false, follow: false },
};

export default function ResetPasswordLayout({ children }: { children: React.ReactNode }) {
  return children;
}
