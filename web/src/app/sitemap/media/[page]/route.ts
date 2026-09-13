// Карта файлов (постранично): страницы `/media/{id}` + превью для Google Изображений.
//
// Превью отдаём только у открытых файлов: у премиум-файла `thumb_url` — размытый
// вариант, и в выдаче картинок он выглядит как «дефект».
import { getSitemapMediaPage } from "@/lib/data";
import { SITEMAP_PAGE_SIZE, SITE_URL, previewUrl, xmlResponse, xmlUrlset } from "@/lib/sitemap";

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
  const data = await getSitemapMediaPage(page, SITEMAP_PAGE_SIZE);
  const entries = data.items.map((media) => ({
    loc: `${SITE_URL}/media/${media.id}`,
    lastmod: media.created_at ? new Date(media.created_at).toISOString() : now,
    changefreq: "weekly",
    priority: 0.5,
    ...(media.locked ? {} : { images: [previewUrl(media.id)] }),
  }));

  return xmlResponse(xmlUrlset(entries));
}
