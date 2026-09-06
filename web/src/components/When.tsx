"use client";

import { useEffect, useState } from "react";

import { formatLocal, formatUtc } from "@/lib/format";

/**
 * Локальное время без hydration-mismatch: во время SSR и первой отрисовки
 * показывается UTC, после монтирования — локальная таймзона пользователя.
 */
export default function When({ iso, className }: { iso: string; className?: string }) {
  const [text, setText] = useState(() => formatUtc(iso));

  useEffect(() => {
    setText(formatLocal(iso));
  }, [iso]);

  return (
    <time dateTime={iso} className={className} title={text}>
      {text}
    </time>
  );
}
