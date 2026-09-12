import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import Footer from "@/components/Footer";
import Header from "@/components/Header";
import MobileNav from "@/components/MobileNav";
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
  title: {
    default: "DREDGE — архив // отбор // доступ",
    template: "%s · DREDGE",
  },
  description: "Медиа-архив: фото и видео с разделов, треды, топ.",
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
