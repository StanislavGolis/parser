import { NextResponse, type NextRequest } from "next/server";

import { PUBLIC_PATHS, SITE_CLOSED } from "@/lib/env";

/**
 * Старые адреса разделов slivach → короткие.
 *
 * Разделы источника раньше назывались `slivach-<категория>` (`/board/slivach-asmr`),
 * теперь префикс убран (миграция `c4d5e6f7a8b9`) и адрес стал `/board/asmr`.
 * Ссылки на старые адреса живут в поиске и в закладках зрителей, поэтому ведём с
 * них постоянным редиректом (308).
 *
 * Делаем это в middleware, а не в самой странице: страница стримится
 * (`app/loading.tsx`), заголовки уходят раньше, чем рендер доходит до редиректа,
 * и ответ остался бы `200`. Middleware решает это до рендера.
 *
 * Здесь же живут два режима модели Dredger 2.0:
 * - `SITE_MODE=closed` — сайт закрыт: анонимные запросы на `/login`, у всех
 *   ответов `X-Robots-Tag: noindex` (обход не закрываем сразу: робот должен
 *   увидеть `noindex`, иначе страницы останутся в выдаче — см. план §5);
 * - `SITE_MODE=public` — прежнее поведение плюс проверка существования страницы,
 *   чтобы не отдавать «мягкий» 200 на несуществующие `/t/…`, `/media/…`, `/board/…`.
 */
const API_BASE = (process.env.API_BASE_SERVER ?? "").replace(/\/+$/, "");

/** Микро-кэш проверок: один адрес не дёргает API на каждый заход. */
const CHECK_TTL_MS = 60_000;
const CHECK_CACHE = new Map<string, { expires: number; ok: boolean }>();

/** true — ресурс есть, false — 404, null — проверить не удалось (пропускаем). */
async function resourceExists(base: string, path: string): Promise<boolean | null> {
  const cached = CHECK_CACHE.get(path);
  if (cached && cached.expires > Date.now()) return cached.ok;

  try {
    const res = await fetch(`${base}${path}`, {
      headers: { accept: "application/json" },
      cache: "no-store",
    });
    if (res.status === 404) {
      CHECK_CACHE.set(path, { expires: Date.now() + CHECK_TTL_MS, ok: false });
      return false;
    }
    // Ошибки сервера не запоминаем: пусть следующая попытка проверит снова
    if (res.ok) CHECK_CACHE.set(path, { expires: Date.now() + CHECK_TTL_MS, ok: true });
    return true;
  } catch {
    return null;
  }
}

/** Честный 404 до рендера (страница не стримится — статус не «мягкий»). */
function notFound(): NextResponse {
  return new NextResponse("Страница не найдена", {
    status: 404,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "x-robots-tag": "noindex",
    },
  });
}

/** Заголовок для закрытого режима: робот обязан увидеть noindex (см. план §5). */
const NOINDEX_HEADER = "noindex, nofollow, noarchive";

function withNoIndex(response: NextResponse): NextResponse {
  response.headers.set("x-robots-tag", NOINDEX_HEADER);
  return response;
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // 1. Старые адреса разделов slivach → короткие (308). Редирект не требует входа.
  const legacy = /^\/board\/slivach-(.+)$/.exec(pathname);
  if (legacy) {
    const url = request.nextUrl.clone();
    url.pathname = `/board/${legacy[1]}`;
    // `?sort=`/`?thread=` переносятся как есть: параметры просмотра не теряются
    return NextResponse.redirect(url, 308);
  }

  // ── Закрытый режим (Dredger 2.0): всё за логином ───────────────────────────
  if (SITE_CLOSED) {
    const isPublic = PUBLIC_PATHS.some(
      (path) => pathname === path || pathname.startsWith(`${path}/`),
    );
    const hasSession = Boolean(request.cookies.get("sid")?.value);

    if (!isPublic && !hasSession) {
      const url = request.nextUrl.clone();
      url.pathname = "/login";
      url.search = "";
      // `next` — чтобы после входа вернуть пользователя туда, куда он шёл
      if (pathname !== "/") url.searchParams.set("next", pathname);
      return withNoIndex(NextResponse.redirect(url, 307));
    }

    // Сессия есть — пусть страница решает сама; наружу смотрим без индексации
    return withNoIndex(NextResponse.next());
  }

  // ── Публичный режим: прежнее поведение ─────────────────────────────────────
  // API-модуль web недоступен из edge-рантайма, поэтому адрес берём из env, а
  // если его нет — идём на свой origin (nginx всё равно проксирует /api на api).
  const base = API_BASE || request.nextUrl.origin;

  // Страница треда: `/t/123` и `/t/123-тема-треда`
  const thread = /^\/t\/([^/]+)\/?$/.exec(pathname);
  if (thread) {
    const id = /^(\d{1,12})(?:-|$)/.exec(decodeURIComponent(thread[1]));
    const numeric = id ? Number(id[1]) : Number.NaN;
    if (!Number.isFinite(numeric) || numeric <= 0) return notFound();
    return (await resourceExists(base, `/api/v1/threads/${numeric}`)) === false
      ? notFound()
      : NextResponse.next();
  }

  // Страница файла
  const media = /^\/media\/([^/]+)\/?$/.exec(pathname);
  if (media) {
    const numeric = Number(media[1]);
    if (!Number.isFinite(numeric) || numeric <= 0) return notFound();
    return (await resourceExists(base, `/api/v1/media/${numeric}`)) === false
      ? notFound()
      : NextResponse.next();
  }

  // Раздел: `/board/{slug}` (после редиректа выше)
  const board = /^\/board\/([^/]+)\/?$/.exec(pathname);
  if (board) {
    const slug = decodeURIComponent(board[1]);
    return (await resourceExists(base, `/api/v1/boards/${encodeURIComponent(slug)}/threads?per_page=1`)) === false
      ? notFound()
      : NextResponse.next();
  }

  return NextResponse.next();
}

export const config = {
  // Все страницы, кроме служебного: `_next`, API (его закрывает FastAPI в закрытом
  // режиме), входа, healthz, robots, иконок сайта и файла ключа IndexNow.
  // Формат `:path*` и regexp — то, что Next гарантированно подхватывает.
  matcher: [
    "/((?!_next|api|auth|login|healthz|robots\\.txt|icon\\.png|apple-icon\\.png|logo\\.png|favicon|indexnow-key).*)",
  ],
};
