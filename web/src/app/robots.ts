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
 * Закрытый режим (Dredger 2.0): `Disallow: /` включается **вторым шагом** (шаг 4
 * плана, через 2–4 недели). Сейчас важно, чтобы робот мог обойти страницы и
 * увидеть `X-Robots-Tag: noindex`: при закрытом обходе он этого не узнает и
 * страницы останутся в выдаче месяцами.
 */
export default function robots(): MetadataRoute.Robots {
  if (SITE_CLOSED) {
    // Обход не закрываем: аноним получает 307 на /login и noindex — этого достаточно,
    // чтобы страницы выпали из индекса. Служебное закрываем как обычно.
    return {
      rules: [
        {
          userAgent: "*",
          disallow: ["/admin", "/api/", "/profile", "/marks", "/favorites", "/search"],
        },
      ],
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
