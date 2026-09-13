import type { MetadataRoute } from "next";

import { getBoards, getFeedPage } from "@/lib/data";
import { SITE_URL, absoluteUrl } from "@/lib/env";

/** Лимит страницы ленты в API: `per_page <= 100`. */
const FEED_PAGE_MAX = 100;
/** Сколько свежих файлов попадает в карту сайта (5 запросов к API). */
const MEDIA_IN_SITEMAP = 500;

export const revalidate = 3600; // пересобираем раз в час
// Генерируем по запросу: карта должна сразу содержать разделы и свежие файлы,
// а не пустой снимок времени сборки.
export const dynamic = "force-dynamic";

/**
 * sitemap.xml: публичные страницы + разделы + свежие файлы.
 * Персональные и служебные страницы (админка, профиль, метки, поиск) не включаем —
 * они закрыты и в robots.txt.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();

  const pages: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/`, lastModified: now, changeFrequency: "hourly", priority: 1 },
    { url: `${SITE_URL}/new`, lastModified: now, changeFrequency: "hourly", priority: 0.9 },
    { url: `${SITE_URL}/boards`, lastModified: now, changeFrequency: "daily", priority: 0.8 },
    { url: `${SITE_URL}/top`, lastModified: now, changeFrequency: "daily", priority: 0.7 },
  ];

  // Данные могут быть недоступны (API лежит) — карта сайта обязана отвечать,
  // поэтому при сбое отдаём хотя бы статические адреса.
  try {
    const pagesCount = Math.ceil(MEDIA_IN_SITEMAP / FEED_PAGE_MAX);
    const [boards, ...feeds] = await Promise.all([
      getBoards(),
      ...Array.from({ length: pagesCount }, (_, i) => getFeedPage(i + 1, FEED_PAGE_MAX)),
    ]);

    const boardPages: MetadataRoute.Sitemap = boards.map((b) => ({
      url: `${SITE_URL}/board/${b.slug}`,
      lastModified: now,
      changeFrequency: "daily",
      priority: 0.7,
    }));

    // В карту попадают и превью файлов (images): они отдаются нашим API и открыты
    // роботам — без этого ссылки на изображения в поиске не появляются.
    const mediaPages: MetadataRoute.Sitemap = feeds
      .flatMap((feed) => feed.items)
      .slice(0, MEDIA_IN_SITEMAP)
      .map((m) => {
        const preview = absoluteUrl(m.web_url ?? m.thumb_url);
        return {
          url: `${SITE_URL}/media/${m.id}`,
          lastModified: m.created_at ? new Date(m.created_at) : now,
          changeFrequency: "weekly" as const,
          priority: 0.5,
          ...(preview ? { images: [preview] } : {}),
        };
      });

    return [...pages, ...boardPages, ...mediaPages];
  } catch {
    return pages;
  }
}
