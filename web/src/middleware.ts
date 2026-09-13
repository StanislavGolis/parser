import { NextResponse, type NextRequest } from "next/server";

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
 */
export function middleware(request: NextRequest) {
  const legacy = /^\/board\/slivach-(.+)$/.exec(request.nextUrl.pathname);
  if (!legacy) return NextResponse.next();

  const url = request.nextUrl.clone();
  url.pathname = `/board/${legacy[1]}`;
  // `?sort=`/`?thread=` переносятся как есть: параметры просмотра не теряются
  return NextResponse.redirect(url, 308);
}

export const config = {
  // Только старые адреса разделов slivach — остальные страницы не трогаем
  matcher: ["/board/slivach-:rest*"],
};
