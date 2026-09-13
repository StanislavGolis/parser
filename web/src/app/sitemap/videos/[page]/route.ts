// Карта видео: отдельный слой выдачи (видео-карусели) — нужен `<video:video>`.
//
// В карту попадают только открытые видео с готовым mp4 и длительностью: у
// премиум-файлов поток закрыт (робот получил бы 403), а без mp4 элемент
// `<video:video>` бессмыслен.
import { getSitemapVideoPage } from "@/lib/data";
import { SITEMAP_PAGE_SIZE, SITE_URL, pagesFor, previewUrl, xmlEscape, xmlResponse } from "@/lib/sitemap";

export const revalidate = 3600;

interface PageProps {
  params: { page: string };
}

export async function GET(_request: Request, { params }: PageProps): Promise<Response> {
  const page = Number.parseInt(params.page.replace(/\.xml$/, ""), 10);
  if (!Number.isFinite(page) || page < 1) {
    return new Response("Not found", { status: 404 });
  }

  const now = new Date().toISOString();
  const data = await getSitemapVideoPage(page, SITEMAP_PAGE_SIZE);
  // 404 только если API ответил: при сбое карта остаётся пустой, но живой
  if (data.total > 0 && page > pagesFor(data.total)) {
    return new Response("Not found", { status: 404 });
  }

  const lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:video="http://www.google.com/schemas/sitemap-video/1.1">',
  ];
  for (const video of data.items) {
    const loc = `${SITE_URL}/media/${video.id}`;
    const title = `Видео №${video.id} · медиа-архив DREDGER`;
    const description = `Видео ${video.id} из архива разделов: просмотр, превью и метаданные файла.`;
    lines.push("<url>");
    lines.push(`<loc>${xmlEscape(loc)}</loc>`);
    lines.push(`<lastmod>${video.created_at ? new Date(video.created_at).toISOString() : now}</lastmod>`);
    lines.push("<video:video>");
    lines.push(`<video:thumbnail_loc>${xmlEscape(previewUrl(video.id))}</video:thumbnail_loc>`);
    lines.push(`<video:title>${xmlEscape(title)}</video:title>`);
    lines.push(`<video:description>${xmlEscape(description)}</video:description>`);
    // Поток отдаём через наш прокси: бакет роботу не раскрываем
    lines.push(`<video:content_loc>${xmlEscape(`${SITE_URL}/api/v1/media/${video.id}/asset/video`)}</video:content_loc>`);
    if (video.duration_seconds) {
      lines.push(`<video:duration>${Math.max(1, Math.round(video.duration_seconds))}</video:duration>`);
    }
    lines.push("<video:family_friendly>no</video:family_friendly>");
    lines.push("</video:video>");
    lines.push("</url>");
  }
  lines.push("</urlset>");

  return xmlResponse(`${lines.join("\n")}\n`);
}
