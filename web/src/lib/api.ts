import { apiPathForClient } from "./env";

export class ApiError extends Error {
  status: number;
  /** detail из JSON-ответа FastAPI (если есть). */
  detail?: string;
  /** Операцию можно повторить принудительно (detail.can_force, например добавление раздела). */
  canForce: boolean;

  constructor(status: number, message: string, detail?: string, canForce = false) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.canForce = canForce;
  }
}

interface SendOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  /** Admin-токен (Bearer) для админ-эндпоинтов. */
  token?: string;
  signal?: AbortSignal;
}

/**
 * Запрос к API из браузера (infinite scroll, view/download, админка).
 * Не использует Data Cache Next.js; куки (тот же origin) передаются браузером.
 */
export async function apiSend<T>(path: string, options: SendOptions = {}): Promise<T> {
  const { method = "GET", body, token, signal } = options;
  const url = apiPathForClient(path);

  const headers: Record<string, string> = { accept: "application/json" };
  if (body !== undefined) headers["content-type"] = "application/json";
  if (token) headers["authorization"] = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
      signal,
    });
    // Однократный повтор при rate limit: лимит общий на IP, и в момент открытия
    // ленты параллельные запросы превью легко упираются в него.
    if (res.status === 429) {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      res = await fetch(url, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        cache: "no-store",
        signal,
      });
    }
  } catch (err) {
    throw new ApiError(0, `Сеть недоступна (${url}): ${err instanceof Error ? err.message : err}`);
  }
  if (!res.ok) {
    let detail: string | undefined;
    let canForce = false;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data?.detail === "string") {
        detail = data.detail;
      } else if (data?.detail && typeof data.detail === "object") {
        // Структурированная ошибка: {message, can_force}
        const obj = data.detail as { message?: unknown; can_force?: unknown };
        if (typeof obj.message === "string") detail = obj.message;
        canForce = obj.can_force === true;
      }
    } catch {
      /* тело не JSON */
    }
    throw new ApiError(
      res.status,
      detail ?? `API ${res.status}: ${res.statusText}`,
      detail,
      canForce,
    );
  }
  return (await res.json()) as T;
}

/** GET к API из браузера. */
export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return apiSend<T>(path, { signal });
}

/** POST к API из браузера. */
export async function apiPost<T>(path: string, body?: unknown, token?: string): Promise<T> {
  return apiSend<T>(path, { method: "POST", body, token });
}

/** PATCH к API из браузера. */
export async function apiPatch<T>(path: string, body?: unknown, token?: string): Promise<T> {
  return apiSend<T>(path, { method: "PATCH", body, token });
}

/** DELETE к API из браузера. */
export async function apiDelete<T>(path: string, token?: string): Promise<T> {
  return apiSend<T>(path, { method: "DELETE", token });
}
