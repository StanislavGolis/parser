import { getBoards, getFeedPage, getThreadRefPage } from "@/lib/data";
import { SITE_URL, absoluteUrl } from "@/lib/env";

/**
 * sitemap.xml: публичные страницы + разделы + свежие файлы с превью.
 *
 * Отдаём XML вручную (а не `MetadataRoute.Sitemap`), потому что в Next 14 у
 * штатного sitemap нет поддержки `images` — а нам важно отдать роботу ссылки
 * на превью файлов (без них картинки не попадают в поиск).
 *
 * Персональные и служебные страницы (админка, профиль, метки, поиск) не включаем —
 * они закрыты и в robots.txt.
 */

/** Лимит страницы ленты в API: `per_page <= 100`. */
const FEED_PAGE_MAX = 100;
/** Сколько свежих файлов попадает в карту сайта (5 запросов к API). */
const MEDIA_IN_SITEMAP = 500;
/** Сколько тредов попадает в карту сайта: у них есть текст (тема/описание). */
const THREADS_IN_SITEMAP = 1000;

export const revalidate = 3600; // пересобираем раз в час
// Генерируем по запросу: карта должна сразу содержать разделы и свежие файлы,
// а не пустой снимок времени сборки.
export const dynamic = "force-dynamic";

interface SitemapEntry {
  loc: string;
  lastmod: string;
  changefreq: string;
  priority: number;
  /** Превью файла: `<image:image>` (Google Изображения). */
  images?: string[];
}

/** Экранирование текста и атрибутов XML. */
function xmlEscape(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function serialize(entries: SitemapEntry[]): string {
  const withImages = entries.some((entry) => entry.images?.length);
  const lines = ['<?xml version="1.0" encoding="UTF-8"?>'];
  lines.push(
    withImages
      ? '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
      : '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
  );
  for (const entry of entries) {
    lines.push("<url>");
    lines.push(`<loc>${xmlEscape(entry.loc)}</loc>`);
    lines.push(`<lastmod>${entry.lastmod}</lastmod>`);
    lines.push(`<changefreq>${entry.changefreq}</changefreq>`);
    lines.push(`<priority>${entry.priority}</priority>`);
    for (const image of entry.images ?? []) {
      lines.push(`<image:image><image:loc>${xmlEscape(image)}</image:loc></image:image>`);
    }
    lines.push("</url>");
  }
  lines.push("</urlset>");
  return `${lines.join("\n")}\n`;
}

export async function GET(): Promise<Response> {
  const now = new Date().toISOString();
  const entries: SitemapEntry[] = [
    { loc: `${SITE_URL}/`, lastmod: now, changefreq: "hourly", priority: 1 },
    { loc: `${SITE_URL}/new`, lastmod: now, changefreq: "hourly", priority: 0.9 },
    { loc: `${SITE_URL}/boards`, lastmod: now, changefreq: "daily", priority: 0.8 },
    { loc: `${SITE_URL}/top`, lastmod: now, changefreq: "daily", priority: 0.7 },
  ];

  // Данные могут быть недоступны (API лежит) — карта сайта обязана отвечать,
  // поэтому при сбое отдаём хотя бы статические адреса.
  try {
    const pagesCount = Math.ceil(MEDIA_IN_SITEMAP / FEED_PAGE_MAX);
    const [boards, threadRefs, ...feeds] = await Promise.all([
      getBoards(),
      getThreadRefPage(1, THREADS_IN_SITEMAP),
      ...Array.from({ length: pagesCount }, (_, i) => getFeedPage(i + 1, FEED_PAGE_MAX)),
    ]);

    for (const board of boards) {
      entries.push({
        loc: `${SITE_URL}/board/${board.slug}`,
        lastmod: now,
        changefreq: "daily",
        priority: 0.7,
      });
    }

    // Треды: у них есть текст (тема треда у 2ch, название и описание записи у
    // сайтов) — это единственные посадочные страницы под поисковый запрос.
    for (const thread of threadRefs.items) {
      entries.push({
        loc: `${SITE_URL}/t/${thread.thread_id}`,
        lastmod: thread.last_media_at ? new Date(thread.last_media_at).toISOString() : now,
        changefreq: "weekly",
        priority: 0.6,
      });
    }

    for (const media of feeds.flatMap((feed) => feed.items).slice(0, MEDIA_IN_SITEMAP)) {
      // Размытое превью премиум-файлов в карту не отдаём: в Google Изображениях
      // такая картинка выглядит как «дефект» и портит выдачу.
      const preview = media.locked
        ? undefined
        : absoluteUrl(media.web_url ?? media.thumb_url);
      entries.push({
        loc: `${SITE_URL}/media/${media.id}`,
        lastmod: media.created_at ? new Date(media.created_at).toISOString() : now,
        changefreq: "weekly",
        priority: 0.5,
        ...(preview ? { images: [preview] } : {}),
      });
    }
  } catch {
    // отдаём статические адреса — см. выше
  }

  return new Response(serialize(entries), {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      // Минутный кэш на клиенте, часовой — на прокси (совпадает с revalidate).
      "Cache-Control": "public, max-age=0, s-maxage=3600, must-revalidate",
    },
  });
}
