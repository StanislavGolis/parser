// Вход по одноразовой ссылке из Telegram: `/auth/magic?token=…`.
//
// Роут нужен, чтобы перенести браузеру cookie сессии, которую поставил API:
// серверный компонент этого сделать не может, а route handler — может. Ссылка
// одноразовая, но короткое окно (`MAGIC_LINK_REUSE_SECONDS`) считает входом и
// повторный переход: мессенджер открывает ссылку сам, а человек — вторым браузером.
// Если окно уже прошло, возвращаемся на форму входа с `?error=magic` — там видно
// объяснение и кнопка выдачи новой ссылки.
import { NextResponse, type NextRequest } from "next/server";

import { SERVER_API_BASE, SITE_URL } from "@/lib/env";

export const dynamic = "force-dynamic";

/** Свой путь для возврата после входа (защита от open redirect). */
function safeNext(value: string | null): string {
  if (!value) return "/";
  return value.startsWith("/") && !value.startsWith("//") ? value : "/";
}

/**
 * Публичный адрес сайта для редиректов — всегда `SITE_URL`.
 *
 * За nginx `request.url` внутри контейнера указывает на `http://0.0.0.0:3000` (из-за
 * этого браузер получал белый экран), а `X-Forwarded-Proto` приходит как `http`,
 * потому что nginx ходит в контейнер по http. Домен — один (зеркал нет), поэтому
 * берём его из окружения: получается сразу `https://media-archive.example/…` без лишнего редиректа.
 */
function baseUrl(): string {
  return SITE_URL;
}

export async function GET(request: NextRequest): Promise<Response> {
  const token = request.nextUrl.searchParams.get("token") ?? "";
  const next = safeNext(request.nextUrl.searchParams.get("next"));
  const base = baseUrl();
  const loginUrl = new URL("/login", base);

  if (!token) {
    loginUrl.searchParams.set("error", "magic");
    return NextResponse.redirect(loginUrl);
  }

  let res: Response;
  try {
    res = await fetch(
      `${SERVER_API_BASE}/api/v1/auth/magic?token=${encodeURIComponent(token)}`,
      {
        headers: {
          accept: "application/json",
          // Реальный IP посетителя: API ставит его в след сессии (не docker-IP)
          ...(request.headers.get("x-forwarded-for")
            ? { "x-forwarded-for": request.headers.get("x-forwarded-for") as string }
            : {}),
          ...(request.headers.get("user-agent")
            ? { "user-agent": request.headers.get("user-agent") as string }
            : {}),
        },
        cache: "no-store",
      },
    );
  } catch {
    loginUrl.searchParams.set("error", "api");
    return NextResponse.redirect(loginUrl);
  }

  if (!res.ok) {
    loginUrl.searchParams.set("error", "magic");
    return NextResponse.redirect(loginUrl);
  }

  const response = NextResponse.redirect(new URL(next, base));
  // Переносим cookie сессии, которую поставил API (httpOnly, Secure — как выдал)
  const cookies = res.headers.getSetCookie?.() ?? [];
  for (const cookie of cookies) {
    response.headers.append("set-cookie", cookie);
  }
  return response;
}
