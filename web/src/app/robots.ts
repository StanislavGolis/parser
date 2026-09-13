import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/env";

/**
 * robots.txt: индексируем публичный контент (главная, поток, разделы, файлы),
 * закрываем от роботов служебное: админку, API, авторизацию, поиск (тонкие
 * страницы) и личные разделы.
 *
 * Важное исключение: превью файлов отдаются нашим API (`/api/v1/media/{id}/asset/…`),
 * поэтому этот путь явно разрешён — иначе изображения и постеры видео не попадают
 * в поиск (а роботам Google Images нужны именно картинки, а не только HTML).
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        // Разрешения идут до запретов: путь `/api/v1/media/` длиннее, чем `/api/`,
        // поэтому для поисковика он выигрывает (выбирается самое точное правило).
        allow: ["/", "/api/v1/media/"],
        disallow: [
          "/admin",
          "/api/",
          "/login",
          "/profile",
          "/marks",
          "/favorites",
          "/search",
          "/reset-password",
        ],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
