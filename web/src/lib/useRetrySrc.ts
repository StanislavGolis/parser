"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Паузы между повторными загрузками картинки (мс).
 *
 * Сервер ограничивает частоту запросов на IP (429). Окно лимита — минута, поэтому
 * повторяем не сразу, а с растущей паузой: мелкие «залпы» (листание ленты) к этому
 * времени уже рассасываются, и превью появляется само.
 */
export const RETRY_DELAYS = [1500, 6000, 20000];

/** Метка попытки в URL: без неё браузер может отдать из кэша прежнюю ошибку. */
function withAttempt(url: string, attempt: number): string {
  if (attempt <= 0) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}retry=${attempt}`;
}

/**
 * URL картинки с автоматическим повтором при ошибке загрузки.
 *
 * Зачем: при быстром листании ленты пачка запросов упиралась в лимит медиа-запросов,
 * и карточка навсегда показывала «недоступно» — хотя файл на месте. Теперь загрузка
 * повторяется сама (до трёх раз), а `onGiveUp` вызывается, только когда попытки
 * исчерпаны: карточка показывает плейсхолдер, а лайтбокс — кнопку «Попробовать снова».
 */
export function useRetrySrc(
  url: string | undefined,
  onGiveUp?: () => void,
  delays: number[] = RETRY_DELAYS,
) {
  const [attempt, setAttempt] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const giveUp = useRef(onGiveUp);
  giveUp.current = onGiveUp;

  // Сменился файл — начинаем с чистого листа
  useEffect(() => {
    setAttempt(0);
    if (timer.current) clearTimeout(timer.current);
  }, [url]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const retry = useCallback(() => {
    setAttempt((current) => {
      if (current >= delays.length) {
        giveUp.current?.();
        return current;
      }
      const delay = delays[current];
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setAttempt((n) => n + 1), delay);
      return current;
    });
  }, [delays]);

  const reset = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    setAttempt(0);
  }, []);

  return {
    src: url ? withAttempt(url, attempt) : undefined,
    /** `key` для `<img>`: пересоздаём элемент, чтобы браузер не отдал старую ошибку. */
    key: attempt,
    attempt,
    exhausted: attempt >= delays.length,
    retry,
    reset,
  };
}
