// Карта тредов (постранично): у треда есть текст — это посадочные под поиск.
import { getSitemapThreadsPage } from "@/lib/data";
import { SITEMAP_PAGE_SIZE, SITE_URL, xmlResponse, xmlUrlset } from "@/lib/sitemap";

export const revalidate = 3600;

interface PageProps {
  /** Имя страницы вида `1.xml` (карты адресуются с расширением). */
  params: { page: string };
}

export async function GET(_request: Request, { params }: PageProps): Promise<Response> {
  const page = Number.parseInt(params.page.replace(/\.xml$/, ""), 10);
  if (!Number.isFinite(page) || page < 1) {
    return new Response("Not found", { status: 404 });
  }

  const now = new Date().toISOString();
  const data = await getSitemapThreadsPage(page, SITEMAP_PAGE_SIZE);
  const entries = data.items.map((thread) => ({
    loc: `${SITE_URL}/t/${thread.thread_id}`,
    lastmod: thread.last_media_at ? new Date(thread.last_media_at).toISOString() : now,
    changefreq: "weekly",
    priority: 0.6,
  }));

  return xmlResponse(xmlUrlset(entries));
}
