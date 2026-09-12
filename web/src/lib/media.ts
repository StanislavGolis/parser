import { mediaUrl } from "./env";

/** URL превью (thumb-дериватив) с фолбэком на оригинал. */
export function thumbSrc(m: { thumb_url?: string | null; url: string | null }): string | undefined {
  return mediaUrl(m.thumb_url ?? m.url);
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
