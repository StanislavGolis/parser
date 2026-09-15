import type { Metadata } from "next";
import { headers } from "next/headers";
import { Inter, JetBrains_Mono } from "next/font/google";

import AgeGate from "@/components/AgeGate";
import Footer from "@/components/Footer";
import Header from "@/components/Header";
import MobileNav from "@/components/MobileNav";
import Onboarding from "@/components/Onboarding";
import Tracker from "@/components/Tracker";
import { SITE_CLOSED, SITE_URL } from "@/lib/env";
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
    default: "DREDGER — медиа-архив: фото и видео",
    template: "%s · DREDGER",
  },
  description:
    "DREDGER — автоматический медиа-архив: фото и видео с разделов, свежие поступления, топ за день и неделю, поиск по файлам.",
  applicationName: "DREDGER",
  // Коды подтверждения для панелей вебмастера задаются через env — тогда в HTML
  // появляется нужный meta-тег (альтернатива DNS-TXT при регистрации сайта).
  verification: {
    google: process.env.GOOGLE_SITE_VERIFICATION,
    yandex: process.env.YANDEX_VERIFICATION,
  },
  robots: { index: true, follow: true },
  openGraph: {
    siteName: "DREDGER",
    locale: "ru_RU",
    type: "website",
  },
  twitter: { card: "summary_large_image" },
  icons: {
    icon: "/favicon.svg",
  },
};

/**
 * Маркеры поисковых роботов: им возрастное окно не показываем — иначе бот видит
 * интерстициал, закрывающий контент, и за это сайт понижается в выдаче.
 */
const BOT_RE =
  /(googlebot|google-inspectiontool|yandex|bingbot|msnbot|applebot|duckduckbot|baiduspider|slurp|sogou|exabot|petalbot|semrushbot|ahrefsbot|mj12bot|dotbot|crawler|spider|bot)/i;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // Поисковым роботам возрастное окно не показываем: контент они должны получать
  // без шлюза (Google понижает за интерстициалы, закрывающие контент). Проверка
  // серверная — компонент вообще не попадает в разметку и RSC-пейлоад для бота.
  const userAgent = headers().get("user-agent") ?? "";
  const isBot = BOT_RE.test(userAgent);

  return (
    <html lang="ru" className={`${inter.variable} ${jetbrains.variable}`}>
      <body className="flex min-h-[100dvh] flex-col bg-ink-primary font-sans text-text-primary antialiased">
        <Header />
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 pb-24 sm:px-6 md:pb-8">
          {children}
        </main>
        <Footer />
        <MobileNav />
        <Tracker />
        {/* В закрытом режиме (Dredger 2.0) возрастное окно не нужно: контента
            анонимам нет вообще — их уводит на /login middleware. */}
        {isBot || SITE_CLOSED ? null : <AgeGate />}
        {/* Онбординг новичка: один раз, после подтверждения возраста */}
        {isBot || SITE_CLOSED ? null : <Onboarding />}
      </body>
    </html>
  );
}
