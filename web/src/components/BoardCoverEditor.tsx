"use client";

import { useCallback, useEffect, useState } from "react";

import { EyeIcon, SpinnerIcon } from "@/components/icons";
import { ApiError, apiSend } from "@/lib/api";
import { readAdminToken } from "@/lib/adminAuth";
import { mediaUrl } from "@/lib/env";
import type { AdminBoard } from "@/lib/types";

/** Файл-кандидат для превью раздела (ответ `/admin/boards/{slug}/cover-candidates`). */
interface Candidate {
  id: number;
  media_type: string;
  thumb_url: string | null;
}

/** Плиток в мозаике карточки раздела — столько же, сколько выбирает админ. */
const LIMIT = 4;

/**
 * Выбор превью для карточки раздела в каталоге.
 *
 * Каталог показывает мозаику 2×2. По умолчанию в неё попадают 4 самых свежих
 * файла раздела, но раздел должен выглядеть осмысленно, поэтому админ может
 * закрепить конкретные 4 фото: клик по файлу в галерее — плитка занята, клик по
 * плитке — освободить. Порядок плиток = порядок выбора. «Авто» возвращает
 * автоматический подбор.
 */
export default function BoardCoverEditor({
  board,
  busy,
  onSave,
}: {
  board: AdminBoard;
  busy?: boolean;
  onSave: (ids: number[]) => Promise<boolean>;
}) {
  const [picked, setPicked] = useState<number[]>(board.cover_media_ids ?? []);
  const [items, setItems] = useState<Candidate[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);

  const wanted = picked.join(",");

  const load = useCallback(async () => {
    const token = readAdminToken();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      // Уже сохранённые превью до-запрашиваем через `ids`: файл мог быть старым
      // и в свежую выборку не попасть, а плитка без картинки бесполезна.
      const query = new URLSearchParams({ limit: "60" });
      if (wanted) query.set("ids", wanted);
      const data = await apiSend<Candidate[]>(
        `/api/v1/admin/boards/${encodeURIComponent(board.slug)}/cover-candidates?${query}`,
        { token },
      );
      setItems(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось загрузить файлы раздела");
    } finally {
      setLoading(false);
    }
  }, [board.slug, wanted]);

  useEffect(() => {
    void load();
  }, [load]);

  // Сохранённый выбор поменялся извне (например, после сохранения) — синхронизируем
  useEffect(() => {
    setPicked(board.cover_media_ids ?? []);
    setDirty(false);
  }, [board.cover_media_ids]);

  const byId = new Map((items ?? []).map((c) => [c.id, c]));

  function toggle(id: number) {
    setPicked((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= LIMIT) return prev;
      return [...prev, id];
    });
    setDirty(true);
  }

  async function save(ids: number[]) {
    setError(null);
    // `onSave` возвращает false, если админ-API отклонил запрос: тогда выбор
    // остаётся «грязным», а текст ошибки покажет строка раздела.
    const ok = await onSave(ids);
    setDirty(!ok);
  }

  return (
    <div className="mt-3 border-t border-line pt-3">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <span className="dredge-title">Превью раздела</span>
        <span className="text-[11px] text-text-secondary">
          выберите до {LIMIT} фото — они станут мозаикой карточки в каталоге
        </span>
        {loading && !items ? (
          <SpinnerIcon className="h-3.5 w-3.5 animate-spin text-text-muted" />
        ) : null}
      </div>
      {/* Слоты мозаики: порядок = порядок выбора */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="grid w-44 shrink-0 grid-cols-2 grid-rows-2 gap-px overflow-hidden rounded border border-line bg-line">
          {Array.from({ length: LIMIT }, (_, i) => {
            const id = picked[i];
            const src = id ? byId.get(id)?.thumb_url : null;
            return (
              <button
                key={i}
                type="button"
                onClick={() => {
                  if (!id) return;
                  setPicked((prev) => prev.filter((x) => x !== id));
                  setDirty(true);
                }}
                disabled={!id}
                title={id ? "Убрать из превью" : `Слот ${i + 1}: выберите фото в галерее ниже`}
                className={`relative aspect-square w-full bg-ink-tertiary transition-opacity ${
                  id ? "hover:opacity-80" : ""
                }`}
              >
                {src ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={mediaUrl(src)}
                    alt=""
                    aria-hidden
                    loading="lazy"
                    decoding="async"
                    referrerPolicy="no-referrer"
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <span className="flex h-full w-full items-center justify-center font-mono text-[11px] text-text-muted">
                    {i + 1}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        <div className="flex flex-col gap-2 text-xs">
          <button
            type="button"
            className="btn-primary px-3 py-1.5 text-xs"
            disabled={!dirty || busy || picked.length === 0}
            onClick={() => void save(picked)}
          >
            {busy ? (
              <SpinnerIcon className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <EyeIcon className="h-3.5 w-3.5" />
            )}
            Сохранить
          </button>
          <button
            type="button"
            className="btn-ghost px-3 py-1.5 text-xs"
            disabled={busy || (!dirty && (board.cover_media_ids ?? []).length === 0)}
            onClick={() => void save([])}
            title="Вернуть автоматический подбор: 4 самых свежих файла раздела"
          >
            Авто
          </button>
        </div>
      </div>

      {picked.length >= LIMIT ? (
        <p className="mt-2 text-[11px] text-text-muted">
          Все {LIMIT} плитки заняты: снимите лишнюю (клик по плитке), чтобы добавить другую.
        </p>
      ) : null}

      {/* Галерея свежих файлов раздела */}
      <div className="mt-3">
        {error ? <div className="mb-2 text-xs text-accent-danger">{error}</div> : null}
        {items && items.length === 0 ? (
          <p className="text-xs text-text-secondary">
            В разделе пока нет видимых файлов — превью появится автоматически.
          </p>
        ) : null}
        {items && items.length > 0 ? (
          <div className="grid max-h-72 grid-cols-4 gap-1 overflow-y-auto pr-1 sm:grid-cols-6 lg:grid-cols-8">
            {items.map((c) => {
              const index = picked.indexOf(c.id);
              const active = index >= 0;
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => toggle(c.id)}
                  title={
                    active
                      ? `Снять с превью (слот ${index + 1})`
                      : "Сделать превью раздела"
                  }
                  className={`relative aspect-square overflow-hidden rounded border transition-colors ${
                    active ? "border-accent-primary" : "border-line hover:border-line-hover"
                  }`}
                >
                  {c.thumb_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={mediaUrl(c.thumb_url)}
                      alt=""
                      aria-hidden
                      loading="lazy"
                      decoding="async"
                      referrerPolicy="no-referrer"
                      className={`h-full w-full object-cover transition-opacity ${
                        active ? "opacity-100" : "opacity-70 hover:opacity-100"
                      }`}
                    />
                  ) : (
                    <span className="flex h-full w-full items-center justify-center text-[11px] text-text-muted">
                      нет
                    </span>
                  )}
                  {active ? (
                    <span className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded bg-accent-primary font-mono text-[11px] font-bold text-ink-primary">
                      {index + 1}
                    </span>
                  ) : null}
                  {c.media_type === "video" ? (
                    <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1 font-mono text-[10px] uppercase text-text-secondary">
                      video
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
    </div>
  );
}
