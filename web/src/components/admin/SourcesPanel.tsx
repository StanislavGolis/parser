"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiPatch, apiPost, apiSend } from "@/lib/api";
import { useAdminToken } from "@/lib/adminAuth";
import { formatNumber, formatRelative } from "@/lib/format";
import type { ParseRun, SourceInfo } from "@/lib/types";

const POLL_MS = 5000;

const RUN_LABEL: Record<string, string> = {
  running: "идёт",
  ok: "ок",
  error: "ошибка",
  stopped: "остановлен",
};

function errText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return err.detail;
  return err instanceof Error ? err.message : "Ошибка";
}

/** Индикатор источника: живой прогон / ошибка / выключен. */
function sourceIndicator(source: SourceInfo): { cls: string; text: string } {
  if (!source.is_enabled) return { cls: "bg-text-muted", text: "выключен в реестре" };
  if (source.status.alive) return { cls: "bg-accent-secondary", text: "работает" };
  if (source.status.enabled) return { cls: "bg-accent-warning", text: "запущен, но простаивает" };
  return { cls: "bg-line-hover", text: "на паузе" };
}

/** Итоги прогона одной строкой (для журнала). */
function runSummary(run: ParseRun): string {
  const stats = run.stats ?? {};
  const parts: string[] = [];
  if (stats.queued !== undefined) parts.push(`очередь ${formatNumber(Number(stats.queued))}`);
  if (stats.threads_done !== undefined) parts.push(`обработано ${formatNumber(Number(stats.threads_done))}`);
  if (stats.threads_failed) parts.push(`с ошибками ${formatNumber(Number(stats.threads_failed))}`);
  return parts.join(" · ") || "—";
}

function runDuration(run: ParseRun): string {
  if (!run.started_at) return "—";
  const started = new Date(run.started_at).getTime();
  const finished = run.finished_at ? new Date(run.finished_at).getTime() : Date.now();
  const sec = Math.max(0, Math.round((finished - started) / 1000));
  if (sec < 60) return `${sec} с`;
  const min = Math.floor(sec / 60);
  return `${min} мин ${sec % 60} с`;
}

export default function SourcesPanel() {
  const { token, logout } = useAdminToken();
  const [items, setItems] = useState<SourceInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [configDraft, setConfigDraft] = useState<Record<string, string>>({});
  const [configError, setConfigError] = useState<Record<string, string>>({});
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(
    async (t: string) => {
      try {
        const data = await apiSend<{ items: SourceInfo[] }>("/api/v1/admin/sources", { token: t });
        setItems(data.items);
        setError(null);
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) logout();
        else setError(errText(err));
      }
    },
    [logout],
  );

  useEffect(() => {
    if (!token) return;
    void load(token);
    const id = window.setInterval(() => void load(token), POLL_MS);
    return () => window.clearInterval(id);
  }, [token, load]);

  async function patchSource(code: string, body: Record<string, unknown>, label: string) {
    if (!token) return;
    setBusy(code);
    setError(null);
    try {
      await apiPatch(`/api/v1/admin/sources/${encodeURIComponent(code)}`, body, token);
      setNote(`${label}: сохранено`);
      await load(token);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(null);
    }
  }

  async function toggleRun(code: string, enable: boolean) {
    if (!token) return;
    setBusy(code);
    setError(null);
    try {
      await apiPost(`/api/v1/admin/sources/${encodeURIComponent(code)}/${enable ? "start" : "stop"}`, undefined, token);
      setNote(`${code}: прогон ${enable ? "запущен" : "остановлен"}`);
      await load(token);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(null);
    }
  }

  async function saveConfig(code: string) {
    const draft = configDraft[code];
    if (draft === undefined) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(draft);
    } catch (err) {
      setConfigError((prev) => ({ ...prev, [code]: `не JSON: ${errText(err)}` }));
      return;
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      setConfigError((prev) => ({ ...prev, [code]: "нужен JSON-объект вида { … }" }));
      return;
    }
    setConfigError((prev) => ({ ...prev, [code]: "" }));
    await patchSource(code, { config: parsed }, `${code}: конфиг`);
    setConfigDraft((prev) => {
      const next = { ...prev };
      delete next[code];
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-4">
      {error ? (
        <p className="rounded border border-accent-danger/30 bg-red-500/10 px-3 py-2 text-sm text-accent-danger">
          {error}
        </p>
      ) : null}
      {note ? (
        <p className="rounded border border-accent-primary/30 bg-accent-primary/10 px-3 py-2 text-xs text-accent-primary">
          {note}
        </p>
      ) : null}
      {!items ? <p className="py-10 text-center text-sm text-text-secondary">Загружаем…</p> : null}

      {(items ?? []).map((source) => {
        const indicator = sourceIndicator(source);
        const draft = configDraft[source.code];
        return (
          <section key={source.code} className="rounded border border-line bg-ink-secondary">
            <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-2.5">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`inline-block h-2 w-2 rounded-full ${indicator.cls}`}
                    title={indicator.text}
                    aria-hidden
                  />
                  <h3 className="font-mono text-sm font-bold uppercase tracking-wider text-text-primary">
                    {source.code}
                  </h3>
                  <span className="text-xs text-text-secondary">{source.title}</span>
                  <span className="rounded-[3px] bg-ink-tertiary px-1.5 py-0.5 font-mono text-[10px] text-text-muted">
                    {source.kind}
                  </span>
                  <span className="font-mono text-[10px] text-text-muted">{indicator.text}</span>
                </div>
                <p className="mt-0.5 font-mono text-[11px] text-text-muted">
                  {source.base_url || "адрес не задан"} · досок {formatNumber(source.boards_total)} ·
                  файлов {formatNumber(source.media_total)}
                  {source.status.current ? ` · сейчас: /${source.status.current}` : ""}
                </p>
                {progressLine(source) ? (
                  <p className="mt-0.5 font-mono text-[11px] text-accent-secondary">{progressLine(source)}</p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={busy === source.code || !source.is_enabled}
                  onClick={() => void toggleRun(source.code, !source.status.enabled)}
                  className="btn-small px-3 py-1.5 text-xs"
                  title={
                    source.is_enabled
                      ? "Запустить/остановить прогон этого источника (остальные не затрагиваются)"
                      : "Источник исключён из реестра — сначала верните его"
                  }
                >
                  {source.status.enabled ? "Остановить прогон" : "Запустить прогон"}
                </button>
                <button
                  type="button"
                  disabled={busy === source.code}
                  onClick={() =>
                    void patchSource(
                      source.code,
                      { is_enabled: !source.is_enabled },
                      `${source.code}: реестр`,
                    )
                  }
                  className="btn-ghost px-3 py-1.5 text-xs"
                  title="Реестр: выключенный источник не запускается даже кнопкой «Запустить»"
                >
                  {source.is_enabled ? "Исключить из реестра" : "Вернуть в реестр"}
                </button>
              </div>
            </header>

            <div className="grid gap-3 border-b border-line px-4 py-3 sm:grid-cols-2 lg:grid-cols-4">
              <SourceNumberField
                label="расписание, мин"
                value={source.schedule_minutes}
                min={1}
                disabled={busy === source.code}
                onSave={(v) => void patchSource(source.code, { schedule_minutes: v }, `${source.code}: расписание`)}
              />
              <SourceNumberField
                label="лимит, запросов/с"
                value={source.rate_limit_rps}
                min={0.1}
                step={0.1}
                disabled={busy === source.code}
                onSave={(v) => void patchSource(source.code, { rate_limit_rps: v }, `${source.code}: лимит`)}
              />
              <SourceNumberField
                label="бюджет цикла, мин"
                value={source.budget_minutes}
                min={0}
                disabled={busy === source.code}
                onSave={(v) => void patchSource(source.code, { budget_minutes: v }, `${source.code}: бюджет`)}
              />
              <SourceTextField
                label="базовый адрес"
                value={source.base_url}
                disabled={busy === source.code}
                onSave={(v) => void patchSource(source.code, { base_url: v }, `${source.code}: адрес`)}
              />
            </div>


            <div className="border-b border-line px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
                  Конфиг адаптера
                </h4>
                <button
                  type="button"
                  disabled={busy === source.code || draft === undefined}
                  onClick={() => void saveConfig(source.code)}
                  className="btn-small px-3 py-1 text-xs"
                  title="Сохранить настройки адаптера (категории, селекторы, пагинация)"
                >
                  Сохранить конфиг
                </button>
              </div>
              <textarea
                value={draft ?? JSON.stringify(source.config ?? {}, null, 2)}
                onChange={(e) =>
                  setConfigDraft((prev) => ({ ...prev, [source.code]: e.target.value }))
                }
                spellCheck={false}
                rows={4}
                className="mt-2 w-full rounded border border-line bg-ink-tertiary px-2 py-1.5 font-mono text-[11px] text-text-primary"
              />
              {configError[source.code] ? (
                <p className="mt-1 text-xs text-accent-danger">{configError[source.code]}</p>
              ) : null}
            </div>

            <div className="px-4 py-3">
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-text-secondary">
                Журнал прогонов (parse_runs)
              </h4>
              {source.runs.length === 0 ? (
                <p className="text-xs text-text-muted">Прогонов ещё не было.</p>
              ) : (
                <table className="w-full text-left font-mono text-[11px]">
                  <thead className="text-text-muted">
                    <tr>
                      <th className="py-1 pr-3 font-normal">начало</th>
                      <th className="py-1 pr-3 font-normal">статус</th>
                      <th className="py-1 pr-3 font-normal">длительность</th>
                      <th className="py-1 pr-3 font-normal">итог</th>
                      <th className="py-1 font-normal">ошибка</th>
                    </tr>
                  </thead>
                  <tbody className="text-text-secondary">
                    {source.runs.map((run) => (
                      <tr key={run.id} className="border-t border-line/60">
                        <td className="py-1 pr-3" title={run.started_at ?? ""}>
                          {run.started_at ? formatRelative(run.started_at) : "—"}
                        </td>
                        <td
                          className={`py-1 pr-3 ${
                            run.status === "ok"
                              ? "text-accent-secondary"
                              : run.status === "running"
                                ? "text-text-primary"
                                : "text-accent-warning"
                          }`}
                        >
                          {RUN_LABEL[run.status] ?? run.status}
                        </td>
                        <td className="py-1 pr-3">{runDuration(run)}</td>
                        <td className="py-1 pr-3">{runSummary(run)}</td>
                        <td
                          className="max-w-[24rem] truncate py-1 text-text-muted"
                          title={run.error ?? ""}
                        >
                          {run.error ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}


/** Строка прогресса текущего прохода (каталог/файлы, раздел, тред, файлы). */
function progressLine(source: SourceInfo): string {
  const progress = source.status.progress;
  if (!progress) return "";
  const phase = String(progress.phase ?? "");
  const board = progress.board_slug ? `/${progress.board_slug}` : "";
  const thread = progress.thread_id ? `тред ${progress.thread_id}` : "";
  const done = Number(progress.files_done ?? 0);
  const total = Number(progress.files_total ?? 0);
  const files = total > 0 ? `файлы ${done}/${total}` : "";
  const label = phase === "catalog" ? "читаю каталог" : phase === "files" ? "качаю файлы" : phase;
  return [label, board, thread, files].filter(Boolean).join(" · ");
}

/** Числовое поле источника: сохраняем по Enter или уходу фокуса. */
function SourceNumberField({
  label,
  value,
  min,
  step,
  disabled,
  onSave,
}: {
  label: string;
  value: number;
  min?: number;
  step?: number;
  disabled: boolean;
  onSave: (value: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);

  function commit() {
    const parsed = Number(draft);
    if (!Number.isFinite(parsed) || (min !== undefined && parsed < min)) {
      setDraft(String(value));
      return;
    }
    if (parsed !== value) onSave(parsed);
  }

  return (
    <label className="flex flex-col gap-1">
      <span className="font-mono text-[10px] uppercase tracking-wider text-text-muted">{label}</span>
      <input
        type="number"
        value={draft}
        min={min}
        step={step}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
        className="rounded border border-line bg-ink-tertiary px-2 py-1 font-mono text-xs text-text-primary"
      />
    </label>
  );
}

/** Текстовое поле источника (адрес): сохраняем по Enter или уходу фокуса. */
function SourceTextField({
  label,
  value,
  disabled,
  onSave,
}: {
  label: string;
  value: string;
  disabled: boolean;
  onSave: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);

  function commit() {
    const next = draft.trim();
    if (next && next !== value) onSave(next);
    else setDraft(value);
  }

  return (
    <label className="flex flex-col gap-1">
      <span className="font-mono text-[10px] uppercase tracking-wider text-text-muted">{label}</span>
      <input
        type="text"
        value={draft}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
        className="rounded border border-line bg-ink-tertiary px-2 py-1 font-mono text-xs text-text-primary"
      />
    </label>
  );
}

