"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiPost, apiSend } from "@/lib/api";
import { useAdminToken } from "@/lib/adminAuth";
import { parseUtc } from "@/lib/format";
import type { GiveawayItem } from "@/lib/types";

const STATUS_LABELS: Record<string, string> = {
  draft: "черновик",
  announced: "идёт",
  drawn: "разыгран",
  cancelled: "отменён",
};

function errText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return err instanceof Error ? err.message : "Не получилось";
}

/** Дата и время по-человечески: «15.09 19:40». */
function when(iso: string | null): string {
  if (!iso) return "—";
  const time = new Date(parseUtc(iso));
  if (Number.isNaN(time.getTime())) return "—";
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(time.getDate())}.${pad(time.getMonth() + 1)} ${pad(time.getHours())}:${pad(time.getMinutes())}`;
}

/**
 * Розыгрыши премиум-подписки — часть менеджера канала.
 *
 * Подборкой постов и рубриками занимается вкладка «Автопостинг» (см.
 * `TelegramRubrics.tsx`), здесь только конкурсы: анонс, участие из бота, жеребьёвка
 * и пост-итоги.
 */
export default function TelegramExtras() {
  const { token, logout } = useAdminToken();
  const [giveaways, setGiveaways] = useState<GiveawayItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [kind, setKind] = useState("daily");
  const [prizeDays, setPrizeDays] = useState(3);
  const [title, setTitle] = useState("");

  const guard = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) logout();
      else setError(errText(err));
    },
    [logout],
  );

  const load = useCallback(
    async (t: string) => {
      try {
        setGiveaways(
          await apiSend<GiveawayItem[]>("/api/v1/admin/telegram/giveaways", { token: t }),
        );
        setError(null);
      } catch (err) {
        guard(err);
      }
    },
    [guard],
  );

  useEffect(() => {
    if (token) void load(token);
  }, [token, load]);

  async function createGiveaway() {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await apiPost<GiveawayItem>(
        "/api/v1/admin/telegram/giveaways",
        { kind, prize_days: prizeDays, title: title.trim() || undefined },
        token,
      );
      setTitle("");
      await load(token);
    } catch (err) {
      guard(err);
    } finally {
      setBusy(false);
    }
  }

  async function giveawayAction(item: GiveawayItem, action: string) {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await apiPost<GiveawayItem>(
        `/api/v1/admin/telegram/giveaways/${item.id}/${action}`,
        undefined,
        token,
      );
      await load(token);
    } catch (err) {
      guard(err);
    } finally {
      setBusy(false);
    }
  }

  async function announce(item: GiveawayItem) {
    if (!window.confirm("Опубликовать анонс розыгрыша в канале?")) return;
    await giveawayAction(item, "announce");
  }

  async function draw(item: GiveawayItem) {
    if (!window.confirm("Выбрать победителя и выдать премиум? Отменить нельзя.")) return;
    await giveawayAction(item, "draw");
  }

  async function results(item: GiveawayItem) {
    if (!window.confirm("Опубликовать итоги розыгрыша в канале?")) return;
    await giveawayAction(item, "results");
  }

  const field =
    "rounded border border-line bg-ink-tertiary px-2 py-1 text-xs text-text-primary outline-none focus:border-accent-primary";

  return (
    <div className="rounded border border-line bg-ink-secondary p-4">

      {error ? <p className="mt-2 text-xs text-accent-danger">{error}</p> : null}

      {/* ── Розыгрыши премиума ───────────────────────────────────────────── */}
      <div>
        <h3 className="text-sm font-semibold">Розыгрыши премиума</h3>
        <p className="mt-1 text-xs text-text-secondary">
          Участие — через бота: в посте-анонсе кнопка «Участвовать» проверяет подписку
          на канал. Победителю премиум выдаётся сразу, итогами делимся отдельным постом.
        </p>

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-text-secondary">
          <label className="flex items-center gap-1.5">
            тип:
            <select value={kind} onChange={(e) => setKind(e.target.value)} className={field}>
              <option value="daily">суточный</option>
              <option value="weekly">недельный</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5">
            приз, дней:
            <input
              type="number"
              min={1}
              max={30}
              value={prizeDays}
              onChange={(e) => setPrizeDays(Number(e.target.value))}
              className={`${field} w-16`}
            />
          </label>
          <label className="flex items-center gap-1.5">
            название:
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Розыгрыш дня"
              className={`${field} w-56`}
            />
          </label>
          <button
            type="button"
            onClick={() => void createGiveaway()}
            disabled={busy}
            className="btn-primary px-3 py-1.5 text-xs"
          >
            Создать розыгрыш
          </button>
        </div>

        <div className="mt-3 flex flex-col gap-2">
          {(giveaways ?? []).map((item) => (
            <div key={item.id} className="rounded border border-line bg-ink-tertiary p-3">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                <span className="font-semibold">#{item.id} {item.title}</span>
                <span className="text-text-secondary">
                  {item.kind === "weekly" ? "неделя" : "сутки"} · {item.prize_days} дн. ·{" "}
                  {STATUS_LABELS[item.status] ?? item.status} · участников: {item.entries}
                </span>
                <span className="font-mono text-[11px] text-text-muted">
                  до {when(item.ends_at)}
                </span>
                {item.link ? (
                  <a
                    href={item.link}
                    target="_blank"
                    rel="noreferrer"
                    className="text-accent-primary hover:underline"
                  >
                    анонс
                  </a>
                ) : null}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => void announce(item)}
                  disabled={busy || item.status !== "draft"}
                  className="btn-ghost px-2.5 py-1 text-xs"
                >
                  Анонс в канал
                </button>
                <button
                  type="button"
                  onClick={() => void draw(item)}
                  disabled={busy || item.status !== "announced"}
                  className="btn-ghost px-2.5 py-1 text-xs"
                >
                  Разыграть
                </button>
                <button
                  type="button"
                  onClick={() => void results(item)}
                  disabled={busy || item.status !== "drawn"}
                  className="btn-ghost px-2.5 py-1 text-xs"
                >
                  Итоги в канал
                </button>
                {item.status === "drawn" && item.winners?.length ? (
                  <span className="text-xs text-text-secondary">
                    победители: {item.winners.map((win) => String(win.username)).join(", ")}
                  </span>
                ) : null}
              </div>
            </div>
          ))}
          {giveaways && giveaways.length === 0 ? (
            <p className="text-xs text-text-muted">
              Розыгрышей пока нет. Создайте суточный — и нажмите «Анонс в канал».
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
