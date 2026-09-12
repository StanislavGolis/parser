"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Готовность картинки к показу (для blur-up: пока не готово — видна размытая
 * подложка).
 *
 * Одного `onLoad` мало: если картинка уже в кэше браузера (или успела
 * загрузиться до гидратации), событие `load` не придёт и превью навсегда
 * осталось бы прозрачным поверх блюра. Поэтому дополнительно проверяем
 * `complete` при монтировании и на смене файла, а страховочный таймаут
 * закрывает потерянные события — под проявившейся картинкой блюр остаётся,
 * так что «пустого» кадра не будет.
 */
export function useImgLoaded(mediaKey: string | number | null | undefined, timeoutMs = 1500) {
  const [loaded, setLoaded] = useState(false);
  const nodeRef = useRef<HTMLImageElement | null>(null);

  const onLoad = useCallback(() => setLoaded(true), []);

  const setRef = useCallback((node: HTMLImageElement | null) => {
    nodeRef.current = node;
    if (node?.complete && node.naturalWidth > 0) setLoaded(true);
  }, []);

  // Смена файла (перелистывание/догрузка): смотрим, готов ли новый объект.
  useEffect(() => {
    const node = nodeRef.current;
    setLoaded(Boolean(node?.complete && node.naturalWidth > 0));
  }, [mediaKey]);

  // Страховка от потерянного события load.
  useEffect(() => {
    if (loaded) return;
    const timer = setTimeout(() => setLoaded(true), timeoutMs);
    return () => clearTimeout(timer);
  }, [loaded, timeoutMs, mediaKey]);

  return { loaded, onLoad, setRef };
}
