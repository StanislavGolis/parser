// Индекс карт сайта: `/sitemap.xml` перечисляет отдельные карты.
//
// Раньше это был один файл со смешанными адресами (разделы + файлы). Теперь карты
// разбиты по типам страниц и постранично: робот видит, что обновляется, и обходит
// свежие страницы быстрее. Видео вынесены отдельно — им нужен `<video:video>`.
//
// Персональные и служебные страницы (админка, профиль, метки, поиск) не включаем —
// они закрыты и в robots.txt.
import { getSitemapMediaPage, getSitemapThreadsPage, getSitemapVideoPage } from "@/lib/data";
import { SITE_URL, pagesFor, xmlIndex, xmlResponse } from "@/lib/sitemap";

export const revalidate = 3600; // пересобираем раз в час
// Генерируем по запросу: карта должна сразу содержать разделы и свежие файлы,
// а не пустой снимок времени сборки.
export const dynamic = "force-dynamic";

const now = () => new Date().toISOString();

export async function GET(): Promise<Response> {
  // Число страниц узнаём «пробным» запросом: нужен только total
  const [threads, media, videos] = await Promise.all([
    getSitemapThreadsPage(1, 1).catch(() => null),
    getSitemapMediaPage(1, 1).catch(() => null),
    getSitemapVideoPage(1, 1).catch(() => null),
  ]);

  const pages = {
    threads: threads ? pagesFor(threads.total) : 1,
    media: media ? pagesFor(media.total) : 1,
    videos: videos ? pagesFor(videos.total) : 1,
  };

  const maps = [
    { loc: `${SITE_URL}/sitemap/pages.xml`, lastmod: now() },
    ...Array.from({ length: pages.threads }, (_, i) => ({
      loc: `${SITE_URL}/sitemap/threads/${i + 1}.xml`,
      lastmod: now(),
    })),
    ...Array.from({ length: pages.media }, (_, i) => ({
      loc: `${SITE_URL}/sitemap/media/${i + 1}.xml`,
      lastmod: now(),
    })),
    ...Array.from({ length: pages.videos }, (_, i) => ({
      loc: `${SITE_URL}/sitemap/videos/${i + 1}.xml`,
      lastmod: now(),
    })),
  ];

  return xmlResponse(xmlIndex(maps));
}

