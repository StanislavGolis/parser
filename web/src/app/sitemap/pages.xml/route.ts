// Карта статических страниц и разделов: меняется редко, но должна обновляться.
import { getBoards } from "@/lib/data";
import { SITE_CLOSED, SITE_URL, xmlResponse, xmlUrlset } from "@/lib/sitemap";

export const revalidate = 3600;

export async function GET(): Promise<Response> {
  // Закрытый режим: карт нет — сайт не индексируется
  if (SITE_CLOSED) return new Response("Not found", { status: 404 });

  const now = new Date().toISOString();
  const entries = [
    { loc: `${SITE_URL}/`, lastmod: now, changefreq: "hourly", priority: 1 },
    { loc: `${SITE_URL}/new`, lastmod: now, changefreq: "hourly", priority: 0.9 },
    { loc: `${SITE_URL}/boards`, lastmod: now, changefreq: "daily", priority: 0.8 },
    { loc: `${SITE_URL}/top`, lastmod: now, changefreq: "daily", priority: 0.7 },
  ];

  // Список разделов может быть недоступен (API лежит) — карта обязана отвечать
  try {
    const boards = await getBoards();
    for (const board of boards) {
      entries.push({
        loc: `${SITE_URL}/board/${board.slug}`,
        lastmod: now,
        changefreq: "daily",
        priority: 0.7,
      });
    }
  } catch {
    /* отдаём статические адреса */
  }

  return xmlResponse(xmlUrlset(entries));
}
