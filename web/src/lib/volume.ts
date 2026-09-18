"use client";

import { useEffect, type RefObject } from "react";

/**
 * Громкость плеера, выставленная зрителем, — запоминаем.
 *
 * Уровень звука (и «выключен ли звук») переживает перелистывание файлов, переход
 * между страницами и перезагрузку браузера: иначе каждый следующий файл начинал
 * вещать на громкости системы, и её приходилось выкручивать заново.
 *
 * Храним в localStorage — как «продолжить просмотр» (`lib/resume.ts`) и вид
 * каталога: сервер для настройки плеера не нужен, значение не уходит в запросы.
 * Если хранилище недоступно (приватный режим, запрет хранения), функции молча
 * ничего не делают — плеер работает как обычно, просто без памяти.
 */

const KEY = "dredge.volume.v1";

/** Ползунок громкости генерирует десятки событий в секунду — ждём паузу. */
const SAVE_DELAY_MS = 250;

export interface VolumeState {
  /** Уровень 0..1 (как `HTMLMediaElement.volume`). */
  volume: number;
  /** Выключен ли звук кнопкой в плеере. */
  muted: boolean;
}

function clamp(value: number): number {
  if (!Number.isFinite(value)) return 1;
  return Math.min(1, Math.max(0, value));
}

function storage(): Storage | null {
  try {
    if (typeof localStorage === "undefined") return null;
    // Проверяем записью: в приватном режиме/при запрете storage бросает ошибку
    const probe = "__dredge_probe__";
    localStorage.setItem(probe, "1");
    localStorage.removeItem(probe);
    return localStorage;
  } catch {
    return null;
  }
}

/** Сохранённая громкость или `null`, если зритель её ещё не трогал. */
export function readVolume(): VolumeState | null {
  const store = storage();
  if (!store) return null;
  try {
    const raw = store.getItem(KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as Partial<VolumeState>;
    if (typeof data?.volume !== "number") return null;
    return { volume: clamp(data.volume), muted: Boolean(data.muted) };
  } catch {
    return null;
  }
}

/** Запоминает громкость; выключенный звук помним отдельным флагом. */
export function saveVolume(state: VolumeState): void {
  const store = storage();
  if (!store) return;
  try {
    store.setItem(
      KEY,
      JSON.stringify({ volume: clamp(state.volume), muted: state.muted }),
    );
  } catch {
    // Переполнение хранилища — не повод ломать просмотр: просто забудем уровень
  }
}

/**
 * Переносит сохранённую громкость в элемент `<video>`, а изменения зрителя —
 * в хранилище. Слушаем `volumechange`: он ловит и ползунок плеера, и кнопку
 * «звук», и системные клавиши громкости в части браузеров.
 *
 * Пишем с небольшой задержкой (ползунок «выстреливает» десятками событий), а при
 * отписке — если запись не успела — сохраняем последнее значение сразу: зритель
 * мог закрыть просмотр сразу после изменения громкости.
 *
 * Возвращает функцию отписки (её вызывает `useEffect` при размонтировании).
 */
export function attachVolumeMemory(el: HTMLMediaElement): () => void {
  const saved = readVolume();
  if (saved) {
    el.volume = saved.volume;
    el.muted = saved.muted;
  }

  let timer: ReturnType<typeof setTimeout> | null = null;
  const flush = () => saveVolume({ volume: el.volume, muted: el.muted });
  const onChange = () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      flush();
    }, SAVE_DELAY_MS);
  };

  el.addEventListener("volumechange", onChange);
  return () => {
    el.removeEventListener("volumechange", onChange);
    if (timer) {
      clearTimeout(timer);
      flush();
    }
  };
}

/**
 * Хук для плееров: элемент получает сохранённую громкость, а любое изменение
 * запоминается. `ref` указывает на сам `<video>`.
 */
export function useVolumeMemory(ref: RefObject<HTMLMediaElement | null>): void {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    return attachVolumeMemory(el);
  }, [ref]);
}
