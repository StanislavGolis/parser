"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ApiError, apiSend } from "@/lib/api";
import { useAdminToken } from "@/lib/adminAuth";
import { formatBytes, formatNumber } from "@/lib/format";
import type { AdminOverview, MediaCacheStats, ParserStatus } from "@/lib/types";

const POLL_MS = 4000;

function errText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return err.detail;
  return err instanceof Error ? err.message : "Ошибка";
}

/** Карточка-цифра: подпись мелким моно, значение — крупным. */
function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded border border-line bg-ink-secondary/40 px-3 py-2.5">
      <div className="font-mono text-[10px] uppercase tracking-wider text-text-muted">{label}</div>
      <div className="mt-0.5 text-base font-semibold tabular-nums text-text-primary">{value}</div>
      {hint ? <div className="mt-0.5 text-[11px] text-text-muted">{hint}</div> : null}
    </div>
  );
}

/** Быстрые переходы на вкладки админки. */
const SHORTCUTS = [
  {
    href: "/admin/content",
    title: "Контент",
    text: "Разделы, треды, файлы, хранилище, управление парсером",
  },
  {
    href: "/admin?tab=users",
    title: "Пользователи",
    text: "Аккаунты, премиум, блокировки, след сессий (в разработке)",
  },
  {
    href: "/admin?tab=stats",
    title: "Статистика",
    text: "Посещаемость, поведение, источники, воронки (в разработке)",
  },
];

/** Обзор: ключевые цифры архива, состояние парсера и кэша. */
export default function AdminOverviewPanel() {
  const { token } = useAdminToken();
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [parser, setParser] = useState<ParserStatus | null>(null);
  const [cache, setCache] = useState<MediaCacheStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (t: string) => {
    try {
      const [ov, ps, cs] = await Promise.all([
        apiSend<AdminOverview>("/api/v1/admin/overview", { token: t }),
        apiSend<ParserStatus>("/api/v1/admin/parser/status", { token: t }).catch(() => null),
        apiSend<MediaCacheStats>("/api/v1/admin/media-cache", { token: t }).catch(() => null),
      ]);
      setOverview(ov);
      setParser(ps);
      setCache(cs);
      setError(null);
    } catch (err) {
      setError(errText(err));
    }
  }, []);

  useEffect(() => {
    if (!token) return;
    void load(token);
    const id = window.setInterval(() => void load(token), POLL_MS);
    return () => window.clearInterval(id);
  }, [token, load]);

  const totals = overview?.totals ?? null;
  const progress = parser?.progress ?? null;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-xl font-bold">Обзор</h2>
          <p className="mt-0.5 text-xs text-text-secondary">
            Цифры обновляются автоматически ({POLL_MS / 1000} с) без перезагрузки.
          </p>
        </div>
        {overview ? (
          <span className="font-mono text-[11px] text-text-muted">
            срез: {overview.generated_at.replace("T", " ").slice(0, 19)} UTC
          </span>
        ) : null}
      </div>

      {error ? (
        <p className="mb-4 rounded border border-accent-danger/40 bg-accent-danger/10 px-3 py-2 text-sm text-accent-danger">
          {error}
        </p>
      ) : null}

      {totals ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          <Stat
            label="файлов в базе"
            value={formatNumber(totals.media_total)}
            hint={`в хранилище: ${formatNumber(totals.media_in_s3)}`}
          />
          <Stat
            label="нет в S3"
            value={formatNumber(totals.media_missing)}
            hint={`скачано: ${formatNumber(totals.media_downloaded)}`}
          />
          <Stat
            label="тредов в работе"
            value={formatNumber(totals.threads_active)}
            hint={`парсится: ${formatNumber(totals.threads_parsing)} · в очереди: ${formatNumber(
              totals.threads_pending,
            )}`}
          />
          <Stat
            label="мёртвых тредов"
            value={formatNumber(totals.threads_dead)}
            hint={`файлов в каталогах: ${formatNumber(totals.files_in_catalog)}`}
          />
          <Stat
            label="разделов к парсингу"
            value={`${formatNumber(totals.boards_parsed)} / ${formatNumber(totals.boards_total)}`}
          />
          <Stat label="просмотров файлов" value={formatNumber(totals.views_total)} />
          <Stat label="скачиваний" value={formatNumber(totals.downloads_total)} />
          <Stat
            label="парсер"
            value={parser?.alive ? (parser.enabled ? "работает" : "на паузе") : "не запущен"}
            hint={
              parser?.current_board
                ? `/${parser.current_board}${
                    progress?.files_total
                      ? ` · тред ${progress.thread_id}: ${formatNumber(
                          progress.files_done ?? 0,
                        )}/${formatNumber(progress.files_total)}`
                      : ""
                  }`
                : "раздел не выбран"
            }
          />
        </div>
      ) : (
        <p className="font-mono text-xs text-text-muted">загружаем цифры…</p>
      )}

      {cache ? (
        <div className="mt-3 rounded border border-line bg-ink-secondary/40 px-3 py-2.5">
          <div className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
            кэш медиа на диске
          </div>
          <div className="mt-0.5 text-sm text-text-primary">
            {formatBytes(cache.bytes)} из {formatBytes(cache.max_bytes)} ({cache.used_percent}%) ·
            файлов {formatNumber(cache.files)} · попаданий {formatNumber(cache.hits)} / промахов{" "}
            {formatNumber(cache.misses)}
            {cache.warm.status === "running"
              ? ` · прогрев: ${formatNumber(cache.warm.done)}/${formatNumber(cache.warm.total)}`
              : ""}
          </div>
          <div className="mt-0.5 text-[11px] text-text-muted">
            свободно на диске: {formatBytes(cache.disk_free)}
          </div>
        </div>
      ) : null}

      <div className="mt-5 grid grid-cols-1 gap-2 sm:grid-cols-3">
        {SHORTCUTS.map((s) => (
          <Link
            key={s.href}
            href={s.href}
            className="rounded border border-line bg-ink-secondary/40 px-3 py-2.5 transition-colors hover:border-accent-primary"
          >
            <div className="text-sm font-semibold text-text-primary">{s.title} →</div>
            <div className="mt-0.5 text-[11px] text-text-secondary">{s.text}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}
