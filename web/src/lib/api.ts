import { apiPathForClient } from "./env";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * GET к API из браузера (infinite scroll, view/download).
 * Не использует Data Cache Next.js.
 */
export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const url = apiPathForClient(path);
  let res: Response;
  try {
    res = await fetch(url, { cache: "no-store", signal });
  } catch (err) {
    throw new ApiError(0, `Сеть недоступна (${url}): ${err instanceof Error ? err.message : err}`);
  }
  if (!res.ok) {
    throw new ApiError(res.status, `API ${res.status}: ${res.statusText}`);
  }
  return (await res.json()) as T;
}
