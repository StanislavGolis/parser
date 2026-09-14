// Хелперы карт сайта: сериализация XML и склейка адресов.
//
// Карты разбиты по типам страниц (разделы, треды, файлы, видео) и постранично:
// так Google и Яндекс видят стабильные небольшие файлы и быстрее их обходят, а
// ошибка одной карты не ломает весь sitemap.
import { SITE_CLOSED, SITE_URL } from "./env";

// Маршруты карт импортируют адрес сайта и режим отсюда вместе с хелперами — так
// меньше разрозненных импортов в каждом route.ts.
export { SITE_CLOSED, SITE_URL };

/** Адресов в одной карте (протокол допускает 50 000 URL и 50 МБ на файл). */
export const SITEMAP_PAGE_SIZE = 5000;

/** Экранирование значений в XML (адрес, дата). */
export function xmlEscape(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

export interface SitemapEntry {
  loc: string;
  lastmod?: string | null;
  changefreq?: string;
  priority?: number;
  /** Превью для `<image:image>`; у премиум-файлов не передаём. */
  images?: string[];
}

/** URL превью файла через наш API (робот получает картинку того же origin). */
export function previewUrl(mediaId: number): string {
  return `${SITE_URL}/api/v1/media/${mediaId}/asset/thumb`;
}

/** Карта адресов: `<urlset>` с необязательными расширениями image/video. */
export function xmlUrlset(entries: SitemapEntry[]): string {
  const withImages = entries.some((entry) => entry.images?.length);
  const namespaces = [
    'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
    withImages ? 'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"' : "",
  ].filter(Boolean);

  const lines = [`<?xml version="1.0" encoding="UTF-8"?>`, `<urlset ${namespaces.join(" ")}>`];
  for (const entry of entries) {
    lines.push("<url>");
    lines.push(`<loc>${xmlEscape(entry.loc)}</loc>`);
    if (entry.lastmod) lines.push(`<lastmod>${entry.lastmod}</lastmod>`);
    if (entry.changefreq) lines.push(`<changefreq>${entry.changefreq}</changefreq>`);
    if (typeof entry.priority === "number") lines.push(`<priority>${entry.priority}</priority>`);
    for (const image of entry.images ?? []) {
      lines.push(`<image:image><image:loc>${xmlEscape(image)}</image:loc></image:image>`);
    }
    lines.push("</url>");
  }
  lines.push("</urlset>");
  return `${lines.join("\n")}\n`;
}

/** Индекс карт: `<sitemapindex>` со ссылками на отдельные карты. */
export function xmlIndex(maps: Array<{ loc: string; lastmod?: string | null }>): string {
  const lines = [
    `<?xml version="1.0" encoding="UTF-8"?>`,
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
  ];
  for (const map of maps) {
    lines.push("<sitemap>");
    lines.push(`<loc>${xmlEscape(map.loc)}</loc>`);
    if (map.lastmod) lines.push(`<lastmod>${map.lastmod}</lastmod>`);
    lines.push("</sitemap>");
  }
  lines.push("</sitemapindex>");
  return `${lines.join("\n")}\n`;
}

/** Ответ с XML и часовым кэшем на прокси (карты не обязаны быть «живыми»). */
export function xmlResponse(body: string): Response {
  return new Response(body, {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=0, s-maxage=3600, must-revalidate",
    },
  });
}

/** Сколько страниц в карте при известном количестве записей. */
export function pagesFor(total: number, perPage = SITEMAP_PAGE_SIZE): number {
  return Math.max(1, Math.ceil(Math.max(0, total) / perPage));
}
