// Файл ключа IndexNow: поисковик проверяет, что ключ принадлежит сайту.
// Путь не обязан быть `<key>.txt` — в запросе мы указываем keyLocation.
export const dynamic = "force-dynamic";

export function GET(): Response {
  const key = process.env.INDEXNOW_KEY ?? "";
  if (!key) return new Response("Not found", { status: 404 });

  return new Response(key, {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "public, max-age=3600",
    },
  });
}
