"use client";

import { useState } from "react";

import { ApiError, apiSend } from "@/lib/api";

/** Причины жалобы: значения совпадают с API (`src/api/routes/reports.py`). */
const REASONS: Array<{ value: string; label: string; hint?: string }> = [
  { value: "copyright", label: "авторские права", hint: "моё фото/видео без разрешения" },
  { value: "csam", label: "детская безопасность", hint: "контент с несовершеннолетними" },
  { value: "illegal", label: "запрещённый контент", hint: "нарушает закон" },
  { value: "spam", label: "спам или реклама" },
  { value: "other", label: "другое" },
];

/**
 * Кнопка «Пожаловаться» для лайтбокса и страницы файла.
 *
 * Жалоба уходит в очередь модерации (`/admin/reports`). Причина «детская
 * безопасность» закрывает доступ автоматически: файл и его тред скрываются сразу,
 * хеш уходит в блок-лист — контент не ждёт модератора.
 */
export default function ReportButton({ mediaId }: { mediaId: number }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("copyright");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await apiSend(`/api/v1/media/${mediaId}/report`, {
        method: "POST",
        body: {
          reason,
          comment: comment.trim() || undefined,
          page_url: typeof window === "undefined" ? undefined : window.location.pathname,
        },
      });
      setDone(true);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? (err.detail ?? err.message)
          : "Не удалось отправить жалобу — попробуйте позже",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpen(true);
          setDone(false);
          setError(null);
        }}
        className="inline-flex items-center gap-1.5 rounded px-2 py-1 font-mono text-[11px] text-text-secondary transition-colors hover:text-accent-danger"
        aria-label="Пожаловаться на файл"
        title="Пожаловаться: нарушение прав или запрещённый контент"
      >
        пожаловаться
      </button>

      {open ? (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Жалоба на файл"
          onClick={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <div className="w-full max-w-md rounded border border-line bg-ink-secondary p-4">
            {done ? (
              <div className="text-sm text-text-primary">
                <p className="font-semibold">Жалоба отправлена</p>
                <p className="mt-1 text-xs text-text-secondary">
                  Модератор проверит файл. Если жалоба про детскую безопасность — доступ
                  закрыт уже сейчас.
                </p>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="btn-ghost mt-3 px-3 py-1.5 text-xs"
                >
                  Закрыть
                </button>
              </div>
            ) : (
              <>
                <p className="dredge-title">жалоба на файл #{mediaId}</p>
                <p className="mt-1 text-xs text-text-secondary">
                  Опишите, что не так. Жалоба уходит модератору и не публикуется.
                </p>

                <div className="mt-3 flex flex-col gap-1.5">
                  {REASONS.map((item) => (
                    <label
                      key={item.value}
                      className={`flex cursor-pointer items-start gap-2 rounded border px-2.5 py-1.5 text-xs transition-colors ${
                        reason === item.value
                          ? "border-accent-primary bg-accent-primary/10 text-text-primary"
                          : "border-line text-text-secondary hover:text-text-primary"
                      }`}
                    >
                      <input
                        type="radio"
                        name={`report-reason-${mediaId}`}
                        value={item.value}
                        checked={reason === item.value}
                        onChange={() => setReason(item.value)}
                        className="mt-0.5"
                      />
                      <span>
                        {item.label}
                        {item.hint ? (
                          <span className="block text-[10px] text-text-muted">{item.hint}</span>
                        ) : null}
                      </span>
                    </label>
                  ))}
                </div>

                <textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  rows={3}
                  maxLength={2000}
                  placeholder="Комментарий: ссылка на оригинал, детали обращения (необязательно)"
                  className="mt-3 w-full rounded border border-line bg-ink-tertiary px-2.5 py-2 text-xs text-text-primary outline-none focus:border-accent-primary"
                />

                {error ? <p className="mt-2 text-xs text-accent-danger">{error}</p> : null}

                <div className="mt-3 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void submit()}
                    disabled={busy}
                    className="btn-primary px-3 py-1.5 text-xs"
                  >
                    {busy ? "Отправляем…" : "Отправить жалобу"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setOpen(false)}
                    disabled={busy}
                    className="btn-ghost px-3 py-1.5 text-xs"
                  >
                    Отмена
                  </button>
                </div>

                <p className="mt-3 text-[10px] text-text-muted">
                  Требования правообладателей и порядок удаления — в разделе{" "}
                  <a href="/dmca" className="text-accent-primary hover:underline">
                    DMCA
                  </a>
                  .
                </p>
              </>
            )}
          </div>
        </div>
      ) : null}
    </>
  );
}
