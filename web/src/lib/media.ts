import { mediaUrl } from "./env";

/**
 * URL превью: дериватив `thumb`, иначе размытый вариант, а оригинал — только
 * для изображений.
 *
 * Для видео оригинал не подставляем: `<img>` не умеет показывать видеофайл, он
 * падал с ошибкой, и карточка рисовала «недоступно». Если постера у видео нет
 * вовсе, функция вернёт `undefined` — карточка покажет кадр плеером (`MediaCard`).
 */
export function thumbSrc(m: {
  media_type?: string | null;
  thumb_url?: string | null;
  blur_url?: string | null;
  url?: string | null;
}): string | undefined {
  const preview = mediaUrl(m.thumb_url) ?? mediaUrl(m.blur_url);
  if (preview) return preview;
  return m.media_type === "video" ? undefined : mediaUrl(m.url);
}

/**
 * URL размытого плейсхолдера (blur-up): грузится мгновенно (маленький файл),
 * реальное превью проявляется поверх него — сетка не «прыгает».
 */
export function blurSrc(m: { blur_url?: string | null }): string | undefined {
  return mediaUrl(m.blur_url);
}

/** URL оптимизированной версии (web-дериватив) с фолбэком на оригинал. */
export function webSrc(m: { web_url?: string | null; url: string | null }): string | undefined {
  return mediaUrl(m.web_url ?? m.url);
}

/** Премиум-состояние элемента: доступа нет / подписка активна / не премиум. */
export type PremiumState = "locked" | "granted" | null;

/**
 * Разбирает пару полей API (`is_premium` + `locked`) в одно состояние:
 * - «locked»  — премиум-контент, подписки нет: превью блюрится, бейдж с замком;
 * - «granted» — премиум-контент, подписка активна: без блюра, бейдж со звездой;
 * - null      — обычный (не премиум) контент.
 */
export function premiumState(m: {
  is_premium?: boolean | null;
  locked?: boolean | null;
}): PremiumState {
  if (!m.is_premium) return null;
  return m.locked ? "locked" : "granted";
}

/** Только закрытый премиум-контент (для blur/затемнения и CTA). */
export function isLocked(m: { locked?: boolean | null }): boolean {
  return Boolean(m.locked);
}
