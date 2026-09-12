import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/env";

/**
 * robots.txt: индексируем публичный контент (главная, поток, разделы, файлы),
 * закрываем от роботов служебное: админку, API, авторизацию, поиск (тонкие
 * страницы) и личные разделы.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/admin", "/api/", "/login", "/profile", "/marks", "/favorites", "/search"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
