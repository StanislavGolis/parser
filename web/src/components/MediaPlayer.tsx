"use client";

import { useRef } from "react";

import { useVolumeMemory } from "@/lib/volume";

/**
 * Плеер страницы файла: `<video>` с нативными контролами.
 *
 * Отдельный клиентский компонент нужен ради громкости: уровень, выставленный
 * зрителем, запоминается (`lib/volume.ts`), а для этого нужен доступ к
 * DOM-элементу — в серверном компоненте страницы его нет.
 */
export default function MediaPlayer({
  src,
  className = "max-h-[80vh] w-auto max-w-full rounded-lg",
}: {
  src: string;
  className?: string;
}) {
  const ref = useRef<HTMLVideoElement | null>(null);
  useVolumeMemory(ref);

  return (
    <video
      ref={ref}
      src={src}
      controls
      preload="metadata"
      playsInline
      controlsList="nodownload noremoteplayback"
      disablePictureInPicture
      className={className}
    >
      Ваш браузер не поддерживает HTML5-видео.
    </video>
  );
}
