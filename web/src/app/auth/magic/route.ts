// Вход по одноразовой ссылке из Telegram: `/auth/magic?token=…`.
//
// Роут нужен, чтобы перенести браузеру cookie сессии, которую поставил API:
// серверный компонент этого сделать не может, а route handler — может. Ссылка
// одноразовая: повторный переход вернёт 401 и уведёт на форму входа.
import { NextResponse, type NextRequest } from "next/server";

import { SERVER_API_BASE, SITE_URL } from "@/lib/env";

export const dynamic = "force-dynamic";

/** Свой путь для возврата после входа (защита от open redirect). */
function safeNext(value: string | null): string {
  if (!value) return "/";
  return value.startsWith("/") && !value.startsWith("//") ? value : "/";
}

/**
 * Публичный адрес сайта для редиректов.
 *
 * За nginx `request.url` внутри контейнера указывает на `http://0.0.0.0:3000`, и
 * редирект уводил браузер на этот внутренний адрес (белый экран). Поэтому берём
 * хост из заголовков прокси, а если их нет — `SITE_URL` из окружения.
 */
function baseUrl(request: NextRequest): string {
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (!host) return SITE_URL;
  const proto = request.headers.get("x-forwarded-proto") ?? "https";
  return `${proto}://${host}`;
}

export async function GET(request: NextRequest): Promise<Response> {
  const token = request.nextUrl.searchParams.get("token") ?? "";
  const next = safeNext(request.nextUrl.searchParams.get("next"));
  const base = baseUrl(request);
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
