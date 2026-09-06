import { apiPathForClient } from "./env";

export class ApiError extends Error {
  status: number;
  /** detail из JSON-ответа FastAPI (если есть). */
  detail?: string;

  constructor(status: number, message: string, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
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
  } catch (err) {
    throw new ApiError(0, `Сеть недоступна (${url}): ${err instanceof Error ? err.message : err}`);
  }
  if (!res.ok) {
    let detail: string | undefined;
    try {
      const data = (await res.json()) as { detail?: unknown };
      detail = typeof data?.detail === "string" ? data.detail : undefined;
    } catch {
      /* тело не JSON */
    }
    throw new ApiError(res.status, detail ?? `API ${res.status}: ${res.statusText}`, detail);
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
