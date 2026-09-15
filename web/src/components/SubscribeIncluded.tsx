"use client";

import { useEffect, useState } from "react";

import { apiGet } from "@/lib/api";
import { formatNumber, plural } from "@/lib/format";
import type { Board } from "@/lib/types";

/** Строка «что входит»: слева — что именно, справа — конкретика (числа из архива). */
function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 border-b border-line px-4 py-2.5 last:border-b-0">
      <span className="text-sm text-text-primary">{label}</span>
      <span className="font-mono text-[11px] text-text-secondary">{value}</span>
    </div>
  );
}

/**
 * Блок «Что входит» с реальными цифрами архива.
 *
 * Цифры берём из каталога разделов (открытые/закрытые и число файлов в них) — так
 * человек видит, за что платит, вместо общих слов «приватные разделы доступны».
 * Если API не ответил, строки остаются без чисел — это не ошибка страницы.
 */
export default function SubscribeIncluded() {
  const [boards, setBoards] = useState<Board[] | null>(null);

  useEffect(() => {
    let alive = true;
    apiGet<Board[]>("/api/v1/boards")
      .then((rows) => {
        if (alive) setBoards(rows);
      })
      .catch(() => {
        /* без цифр блок всё равно полезен */
      });
    return () => {
      alive = false;
    };
  }, []);

  const free = (boards ?? []).filter((b) => !b.is_premium);
  const paid = (boards ?? []).filter((b) => b.is_premium);
  const sum = (rows: Board[]) => rows.reduce((total, b) => total + (b.media_count || 0), 0);
  const files = (rows: Board[]) => (boards ? `${formatNumber(sum(rows))} файлов` : "—");

  return (
    <div className="mt-3 overflow-hidden rounded border border-line bg-ink-secondary">
      <Row
        label="Открытые разделы"
        value={
          boards
            ? `${files(free)} · ${free.length} ${plural(free.length, ["раздел", "раздела", "разделов"])} — бесплатно`
            : "бесплатно всем вошедшим"
        }
      />
      <Row
        label="Закрытые разделы"
        value={
          boards
            ? `${files(paid)} · ${paid.length} ${plural(paid.length, ["раздел", "раздела", "разделов"])} — по подписке`
            : "по подписке"
        }
      />
      <Row label="Оригиналы и скачивание" value="по подписке, без лимита по числу файлов" />
    </div>
  );
}
