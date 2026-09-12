import { mediaUrl } from "./env";

/** URL превью (thumb-дериватив) с фолбэком на оригинал. */
export function thumbSrc(m: { thumb_url?: string | null; url: string | null }): string | undefined {
  return mediaUrl(m.thumb_url ?? m.url);
}

/** URL оптимизированной версии (web-дериватив) с фолбэком на оригинал. */
export function webSrc(m: { web_url?: string | null; url: string | null }): string | undefined {
  return mediaUrl(m.web_url ?? m.url);
}
