"use client";

import { useState } from "react";

import { DownloadIcon, SpinnerIcon } from "@/components/icons";
import { ApiError, apiGet } from "@/lib/api";
import { mediaUrl } from "@/lib/env";
import type { DownloadResult } from "@/lib/types";

/**
 * Кнопка «Скачать»: отмечает скачивание на бэкенде (/media/{id}/download)
 * и открывает полученный URL файла (через наш API).
 */
export default function DownloadButton({
  mediaId,
  size = "md",
}: {
  mediaId: number;
  size?: "sm" | "md";
}) {
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");

  async function handleDownload() {
    if (state === "loading") return;
    setState("loading");
    try {
      const res = await apiGet<DownloadResult>(`/api/v1/media/${mediaId}/download`);
      if (res?.url) {
        // Открываем URL файла (наш API) как обычное скачивание.
        window.location.assign(mediaUrl(res.url) ?? res.url);
      }
      setState("idle");
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      if (status === 401) {
        // Оригиналы доступны только авторизованным
        setState("idle");
        if (window.confirm("Оригиналы доступны зарегистрированным пользователям. Войти?")) {
          window.location.assign("/login");
        }
      } else if (status === 409 || status === 503) {
        // Файл пока недоступен (нет объекта в S3) — сервер отвечает осознанно.
        setState("idle");
        window.alert("Файл временно недоступен. Попробуйте позже.");
      } else {
        setState("error");
      }
    }
  }

  const cls =
    size === "sm"
      ? "btn-ghost px-3 py-1.5 text-xs"
      : "btn-primary";

  return (
    <button type="button" onClick={handleDownload} disabled={state === "loading"} className={cls}>
      {state === "loading" ? <SpinnerIcon className="h-4 w-4" /> : <DownloadIcon className="h-4 w-4" />}
      <span>{state === "loading" ? "Подготовка…" : state === "error" ? "Ошибка — повторить" : "Скачать"}</span>
    </button>
  );
}
