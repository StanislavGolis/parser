import type { MetadataRoute } from "next";

import { SITE_CLOSED, SITE_URL } from "@/lib/env";

/**
 * robots.txt.
 *
 * Публичный режим: индексируем контент (главная, поток, разделы, файлы), закрываем
 * служебное: админку, API, авторизацию, поиск (тонкие страницы) и личные разделы.
 *
 * Важное исключение в публичном режиме: превью файлов отдаются нашим API
 * (`/api/v1/media/{id}/asset/…`), поэтому этот путь явно разрешён — иначе
 * изображения и постеры видео не попадают в поиск.
 *
 * Закрытый режим (Dredger 2.0): `Disallow: /` — но включается он **вторым шагом**.
 * Сначала сайт отдаёт `X-Robots-Tag: noindex` (middleware), иначе робот не увидит
 * запрет индексации и страницы останутся в выдаче месяцами (см. план §5).
 */
export default function robots(): MetadataRoute.Robots {
  if (SITE_CLOSED) {
    return {
      rules: [{ userAgent: "*", disallow: ["/"] }],
    };
  }

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
