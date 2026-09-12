import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import Footer from "@/components/Footer";
import Header from "@/components/Header";
import MobileNav from "@/components/MobileNav";
import { SITE_URL } from "@/lib/env";
import "./globals.css";

const inter = Inter({
  subsets: ["latin", "cyrillic"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin", "cyrillic"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  // Базовый адрес для canonical/Open Graph: страницы задают относительные пути.
  metadataBase: new URL(SITE_URL),
  title: {
    default: "DREDGE — медиа-архив: фото и видео",
    template: "%s · DREDGE",
  },
  description:
    "DREDGE — автоматический медиа-архив: фото и видео с разделов, свежие поступления, топ за день и неделю, поиск по файлам.",
  applicationName: "DREDGE",
  robots: { index: true, follow: true },
  openGraph: {
    siteName: "DREDGE",
    locale: "ru_RU",
    type: "website",
  },
  twitter: { card: "summary_large_image" },
  icons: {
    icon: "/favicon.svg",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru" className={`${inter.variable} ${jetbrains.variable}`}>
      <body className="flex min-h-screen flex-col bg-ink-primary font-sans text-text-primary antialiased">
        <Header />
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 pb-24 sm:px-6 md:pb-8">
          {children}
        </main>
        <Footer />
        <MobileNav />
      </body>
    </html>
  );
}
