"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiSend } from "@/lib/api";
import { useAdminToken } from "@/lib/adminAuth";
import { formatNumber } from "@/lib/format";
import type {
  StatsContent,
  StatsDevices,
  StatsEvents,
  StatsHealth,
  StatsOverview,
  StatsPages,
  StatsSources,
  StatsTimeseries,
} from "@/lib/types";

/** Периоды отчёта (дни). */
const PERIODS = [
  { days: 1, label: "сутки" },
  { days: 7, label: "7 дней" },
  { days: 30, label: "30 дней" },
  { days: 90, label: "90 дней" },
];

function errText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return err.detail;
  return err instanceof Error ? err.message : "Ошибка";
}

/** Столбик диаграммы: высота пропорциональна значению. */
function Bar({ value, max, title }: { value: number; max: number; title: string }) {
  const height = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 2;
  return (
    <div className="flex h-full flex-1 items-end" title={title}>
      <div
        className="w-full rounded-sm bg-accent-primary/70 transition-all"
        style={{ height: `${height}%` }}
      />
    </div>
  );
}

/** Компактная таблица «подпись — значение» для блоков отчёта. */
function Table({
  title,
  rows,
  hint,
}: {
  title: string;
  rows: Array<[string, string]>;
  hint?: string;
}) {
  return (
    <div className="rounded border border-line bg-ink-secondary/40 p-3">
      <div className="font-mono text-[10px] uppercase tracking-wider text-text-muted">{title}</div>
      {hint ? <div className="mt-0.5 text-[11px] text-text-muted">{hint}</div> : null}
      {rows.length === 0 ? (
        <p className="mt-2 text-xs text-text-muted">данных пока нет</p>
      ) : (
        <div className="mt-2 flex flex-col gap-1">
          {rows.map(([label, value]) => (
            <div key={label} className="flex items-baseline justify-between gap-3 text-xs">
              <span className="min-w-0 truncate text-text-secondary" title={label}>
                {label}
              </span>
              <span className="shrink-0 tabular-nums text-text-primary">{value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Значение с дельтой к прошлому периоду. */
function withDelta(value: number, delta: number | null): string {
  if (delta === null) return formatNumber(value);
  const sign = delta > 0 ? "+" : "";
  return `${formatNumber(value)} (${sign}${delta}%)`;
}

/** Статистика: посещаемость, источники, устройства, события, контент, ошибки API. */
export default function AdminStatsPanel() {
  const { token } = useAdminToken();
  const [days, setDays] = useState(30);
  const [overview, setOverview] = useState<StatsOverview | null>(null);
  const [series, setSeries] = useState<StatsTimeseries | null>(null);
  const [pages, setPages] = useState<StatsPages | null>(null);
  const [sources, setSources] = useState<StatsSources | null>(null);
  const [devices, setDevices] = useState<StatsDevices | null>(null);
  const [events, setEvents] = useState<StatsEvents | null>(null);
  const [content, setContent] = useState<StatsContent | null>(null);
  const [health, setHealth] = useState<StatsHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (t: string, period: number) => {
      setBusy(true);
      setError(null);
      const q = `?days=${period}`;
      const group = period <= 2 ? "hour" : "day";
      try {
        const [ov, ts, pg, src, dev, ev, ct, hl] = await Promise.all([
          apiSend<StatsOverview>(`/api/v1/admin/stats/overview${q}`, { token: t }),
          apiSend<StatsTimeseries>(`/api/v1/admin/stats/timeseries${q}&group=${group}`, {
            token: t,
          }),
          apiSend<StatsPages>(`/api/v1/admin/stats/pages${q}`, { token: t }),
          apiSend<StatsSources>(`/api/v1/admin/stats/sources${q}`, { token: t }),
          apiSend<StatsDevices>(`/api/v1/admin/stats/devices${q}`, { token: t }),
          apiSend<StatsEvents>(`/api/v1/admin/stats/events${q}`, { token: t }),
          apiSend<StatsContent>(`/api/v1/admin/stats/content${q}`, { token: t }),
          apiSend<StatsHealth>("/api/v1/admin/stats/health?days=7", { token: t }),
        ]);
        setOverview(ov);
        setSeries(ts);
        setPages(pg);
        setSources(src);
        setDevices(dev);
        setEvents(ev);
        setContent(ct);
        setHealth(hl);
      } catch (err) {
        setError(errText(err));
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!token) return;
    void load(token, days);
  }, [token, days, load]);

  /** Карточка-цифра (локальная копия — панель живёт отдельно от «Обзора»). */
  function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
    return (
      <div className="rounded border border-line bg-ink-secondary/40 px-3 py-2.5">
        <div className="font-mono text-[10px] uppercase tracking-wider text-text-muted">{label}</div>
        <div className="mt-0.5 text-base font-semibold tabular-nums text-text-primary">{value}</div>
        {hint ? <div className="mt-0.5 text-[11px] text-text-muted">{hint}</div> : null}
      </div>
    );
  }

  const maxVisitors = Math.max(1, ...(series?.points.map((p) => p.visitors) ?? [1]));
  const healthRows: Array<[string, string]> = (health?.items ?? [])
    .filter((item) => item.total > 0)
    .slice(0, 7)
    .map((item) => [
      item.date,
      Object.entries(item.counters)
        .map(([code, count]) => `${code}: ${count}`)
        .join(" · "),
    ]);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">Статистика посещаемости</h2>
          <p className="mt-0.5 text-xs text-text-secondary">
            Своя аналитика: IP хранится только хешем, из реферера — лишь хост, боты в отчёты
            не попадают.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {PERIODS.map((period) => (
            <button
              key={period.days}
              type="button"
              onClick={() => setDays(period.days)}
              className={`filter-btn font-mono text-[11px] ${
                days === period.days ? "filter-btn-active" : ""
              }`}
            >
              {period.label}
            </button>
          ))}
          <button
            type="button"
            className="btn-ghost px-3 py-1.5 text-xs"
            disabled={busy || !token}
            onClick={() => token && void load(token, days)}
          >
            {busy ? "Обновляем…" : "Обновить"}
          </button>
        </div>
      </div>

      {error ? (
        <p className="mb-4 rounded border border-accent-danger/40 bg-accent-danger/10 px-3 py-2 text-sm text-accent-danger">
          {error}
        </p>
      ) : null}

      {overview ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <Stat
            label="посетители"
            value={withDelta(overview.visitors, overview.delta.visitors)}
            hint={`новых ${formatNumber(overview.new_visitors)} · вернувшихся ${formatNumber(
              overview.returning_visitors,
            )}`}
          />
          <Stat label="визиты" value={withDelta(overview.visits, overview.delta.visits)} />
          <Stat
            label="просмотры страниц"
            value={withDelta(overview.pageviews, overview.delta.pageviews)}
            hint={`${overview.pages_per_visit} на визит`}
          />
          <Stat label="события" value={formatNumber(overview.events)} />
          <Stat label="вошедшие" value={formatNumber(overview.registered)} hint="уникальных аккаунтов" />
          <Stat
            label="период"
            value={`${overview.days} дн.`}
            hint={`срез: ${overview.generated_at.slice(0, 16).replace("T", " ")} UTC`}
          />
        </div>
      ) : (
        <p className="font-mono text-xs text-text-muted">загружаем…</p>
      )}

      {series && series.points.length > 0 ? (
        <div className="mt-4 rounded border border-line bg-ink-secondary/40 p-3">
          <div className="flex items-baseline justify-between gap-3">
            <span className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
              посетители по {series.group === "hour" ? "часам" : "дням"}
            </span>
            <span className="font-mono text-[10px] text-text-muted">
              максимум: {formatNumber(maxVisitors)}
            </span>
          </div>
          <div className="mt-3 flex h-32 items-end gap-0.5">
            {series.points.map((point) => (
              <Bar
                key={point.t}
                value={point.visitors}
                max={maxVisitors}
                title={`${point.t.slice(0, 16).replace("T", " ")} · посетителей ${point.visitors}, визитов ${point.visits}, страниц ${point.pageviews}`}
              />
            ))}
          </div>
        </div>
      ) : null}

      <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-3">
        <Table
          title="страницы"
          hint="просмотры / посетители"
          rows={(pages?.items ?? [])
            .slice(0, 12)
            .map((page) => [
              page.path,
              `${formatNumber(page.views)} / ${formatNumber(page.visitors)}`,
            ])}
        />
        <Table
          title="источники"
          hint={
            sources && sources.utm.length > 0
              ? `utm: ${sources.utm.map((u) => `${u.source} (${u.visits})`).join(", ")}`
              : "внешние сайты и прямые заходы"
          }
          rows={(sources?.referrers ?? []).map((ref) => [
            ref.host,
            `${formatNumber(ref.visits)} визитов`,
          ])}
        />
        <Table
          title="устройства"
          rows={(devices?.devices ?? []).map((d) => [
            d.name,
            `${formatNumber(d.visitors)} посетителей`,
          ])}
        />
        <Table
          title="браузеры"
          rows={(devices?.browsers ?? []).map((d) => [d.name, formatNumber(d.hits)])}
        />
        <Table
          title="события интерфейса"
          hint="просмотр файла, фильтры, скачивание, метки"
          rows={(events?.items ?? []).map((e) => [e.event, formatNumber(e.hits)])}
        />
        <Table title="ошибки API (7 дней)" hint="429 — лимиты, 5xx — сбои" rows={healthRows} />
        <Table
          title="топ файлов: просмотры"
          rows={(content?.views ?? []).map((m) => [
            `/${m.board} · ${m.name}`,
            formatNumber(m.count),
          ])}
        />
        <Table
          title="топ файлов: скачивания"
          rows={(content?.downloads ?? []).map((m) => [
            `/${m.board} · ${m.name}`,
            formatNumber(m.count),
          ])}
        />
        <Table
          title="топ файлов: метки"
          rows={(content?.marks ?? []).map((m) => [
            `/${m.board} · ${m.name}`,
            formatNumber(m.count),
          ])}
        />
        <Table
          title="разделы по просмотрам"
          rows={(content?.boards ?? []).map((b) => [`/${b.board}`, formatNumber(b.views)])}
        />
      </div>
    </div>
  );
}
