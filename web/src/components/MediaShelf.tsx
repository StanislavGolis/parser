"use client";

import { useState } from "react";

import Lightbox from "@/components/Lightbox";
import MediaCard from "@/components/MediaCard";
import type { BoardsById, MediaItem } from "@/lib/types";

interface MediaShelfProps {
  items: MediaItem[];
  boardsById?: BoardsById;
  /** Показывать бейдж [ТОП] на карточках. */
  showTop?: boolean;
}

/**
 * Полка из фиксированного числа карточек с собственным лайтбоксом.
 * Используется на главной («Популярное сейчас»); догрузки страниц здесь нет.
 */
export default function MediaShelf({ items, boardsById, showTop = false }: MediaShelfProps) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  const step = (dir: 1 | -1) => {
    setOpenIndex((cur) => {
      if (cur === null || items.length < 2) return cur;
      return (cur + dir + items.length) % items.length;
    });
  };

  return (
    <>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {items.map((media, idx) => (
          <MediaCard
            key={media.id}
            media={media}
            board={boardsById ? boardsById[media.board_id] : undefined}
            showTop={showTop}
            onOpen={() => setOpenIndex(idx)}
          />
        ))}
      </div>

      {openIndex !== null ? (
        <Lightbox
          items={items}
          index={openIndex}
          boardsById={boardsById}
          onClose={() => setOpenIndex(null)}
          onPrev={() => step(-1)}
          onNext={() => step(1)}
          onSelect={(i) => setOpenIndex(i)}
        />
      ) : null}
    </>
  );
}
