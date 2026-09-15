"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiPatch, apiPost, apiSend } from "@/lib/api";
import { useAdminToken } from "@/lib/adminAuth";
import { formatNumber, parseUtc } from "@/lib/format";
import type { AdminPlan, AdminPlans, PaymentItem, PricingPromo } from "@/lib/types";

const PLAN_ORDER = ["week", "month", "year", "forever"];

function errText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return err instanceof Error ? err.message : "Не получилось";
}

/** Дата по-человечески: «15.09 19:40» или «—». */
function when(iso: string | null): string {
  if (!iso) return "—";
  const time = new Date(parseUtc(iso));
  if (Number.isNaN(time.getTime())) return "—";
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(time.getDate())}.${pad(time.getMonth() + 1)} ${pad(time.getHours())}:${pad(time.getMinutes())}`;
}

/** Сумма в рублях: «2 500 ₽». */
function rub(value: number): string {
  return `${formatNumber(value)} ₽`;
}

/**
 * Тарифы и стартовая акция — вкладка «Тарифы».
 *
 * Путь «открытый архив»: Free видит открытые разделы с рекламой, Premium — приватные
 * разделы, скачивание и без рекламы. Цены, сроки и условия акции правятся здесь и
 * вступают в силу сразу: и сайт, и бот читают один и тот же источник.
 */
export default function PlansPanel() {
  const { token, logout } = useAdminToken();
  const [data, setData] = useState<AdminPlans | null>(null);
  const [payments, setPayments] = useState<PaymentItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<Record<string, Partial<AdminPlan>>>({});
  const [promoEnds, setPromoEnds] = useState("");
  const [promoPercent, setPromoPercent] = useState<number | null>(null);
  const [promoLimit, setPromoLimit] = useState<number | null>(null);
  const [grantUser, setGrantUser] = useState("");
  const [grantPlan, setGrantPlan] = useState("month");
  const [grantPercent, setGrantPercent] = useState(0);

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
        setData(await apiSend<AdminPlans>("/api/v1/admin/plans", { token: t }));
        setPayments(
          await apiSend<PaymentItem[]>("/api/v1/admin/plans/payments?limit=30", { token: t }),
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

  function patchPlan(code: string, patch: Partial<AdminPlan>) {
    setDraft((prev) => ({ ...prev, [code]: { ...prev[code], ...patch } }));
  }

  async function savePlan(code: string) {
    if (!token) return;
    const patch = draft[code];
    if (!patch) return;
    setBusy(true);
    setError(null);
    try {
      await apiPatch<AdminPlan>(`/api/v1/admin/plans/${code}`, patch, token);
      setDraft((prev) => {
        const next = { ...prev };
        delete next[code];
        return next;
      });
      await load(token);
    } catch (err) {
      guard(err);
    } finally {
      setBusy(false);
    }
  }

  async function savePromo(patch: Record<string, unknown>) {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await apiPatch<Record<string, unknown>>("/api/v1/admin/plans/promo", patch, token);
      setPromoEnds("");
      setPromoPercent(null);
      setPromoLimit(null);
      await load(token);
    } catch (err) {
      guard(err);
    } finally {
      setBusy(false);
    }
  }

  async function grant() {
    if (!token) return;
    const userId = Number(grantUser);
    if (!userId) {
      setError("Укажите id аккаунта");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiPost<PaymentItem>(
        `/api/v1/admin/plans/${grantPlan}/grant`,
        { user_id: userId, percent: grantPercent },
        token,
      );
      setGrantUser("");
      await load(token);
    } catch (err) {
      guard(err);
    } finally {
      setBusy(false);
    }
  }

  const promo = data?.promo;
  const field =
    "rounded border border-line bg-ink-tertiary px-2 py-1 text-xs text-text-primary outline-none focus:border-accent-primary";
  const plans = [...(data?.plans ?? [])].sort(
    (a, b) => PLAN_ORDER.indexOf(a.code) - PLAN_ORDER.indexOf(b.code),
  );

  return (
    <div className="mt-4 flex flex-col gap-6">
      {error ? <p className="text-xs text-accent-danger">{error}</p> : null}

      {/* Тарифы */}
      <div className="rounded border border-line bg-ink-secondary p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Тарифы</h3>
          <span className="font-mono text-[11px] text-text-muted">
            {data
              ? `оплат: ${formatNumber(data.sales.paid ?? 0)} · сумма: ${rub(data.sales.amount_rub ?? 0)}`
              : "загрузка…"}
          </span>
        </div>
        <p className="mt-1 text-xs text-text-secondary">
          Free видит открытые разделы (с рекламой). Premium открывает приватные разделы,
          скачивание и убирает рекламу. Цена — в рублях: для крипты пересчитывается по курсу
          на момент счёта.
        </p>

        <div className="mt-3 flex flex-col gap-2">
          {plans.map((plan) => {
            const edit = draft[plan.code] ?? {};
            const price = edit.price_rub ?? plan.price_rub;
            const days = edit.days ?? plan.days;
            const active = edit.is_active ?? plan.is_active;
            const promoPercent = promo?.active ? promo.percent : 0;
            const now = Math.max(1, Math.round((price * (100 - promoPercent)) / 100));
            const dirty = Object.keys(edit).length > 0;
            return (
              <div key={plan.code} className="rounded border border-line bg-ink-tertiary p-3">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-text-secondary">
                  <span className="font-semibold text-text-primary">{plan.title}</span>
                  <span className="font-mono text-[11px] text-text-muted">{plan.code}</span>
                  <label className="flex items-center gap-1.5">
                    цена:
                    <input
                      type="number"
                      min={0}
                      value={price}
                      onChange={(e) => patchPlan(plan.code, { price_rub: Number(e.target.value) })}
                      className={`${field} w-24`}
                    />
                    ₽
                  </label>
                  <label className="flex items-center gap-1.5">
                    дней:
                    <input
                      type="number"
                      min={1}
                      value={days}
                      onChange={(e) => patchPlan(plan.code, { days: Number(e.target.value) })}
                      className={`${field} w-20`}
                    />
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={active}
                      onChange={(e) => patchPlan(plan.code, { is_active: e.target.checked })}
                    />
                    показывать
                  </label>
                  {promoPercent ? (
                    <span className="text-accent-secondary">
                      по акции: {rub(now)} (−{promoPercent}%)
                    </span>
                  ) : null}
                  {plan.badge ? <span className="text-accent-warning">{plan.badge}</span> : null}
                  <button
                    type="button"
                    onClick={() => void savePlan(plan.code)}
                    disabled={busy || !dirty}
                    className={
                      dirty ? "btn-primary px-3 py-1.5 text-xs" : "btn-ghost px-3 py-1.5 text-xs"
                    }
                  >
                    Сохранить
                  </button>
                  {dirty ? (
                    <button
                      type="button"
                      onClick={() =>
                        setDraft((prev) => {
                          const next = { ...prev };
                          delete next[plan.code];
                          return next;
                        })
                      }
                      className="text-text-muted hover:text-text-primary"
                    >
                      отменить
                    </button>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Стартовая акция */}
      <div className="rounded border border-line bg-ink-secondary p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Стартовая акция</h3>
          <span className={promo?.active ? "text-xs text-accent-secondary" : "text-xs text-text-muted"}>
            {promo
              ? promo.active
                ? `активна: −${promo.percent}% (осталось оплат: ${promo.paid_left ?? "—"}, дней: ${promo.days_left ?? "—"})`
                : `не активна: ${promo.reason || "—"}`
              : "загрузка…"}
          </span>
        </div>
        <p className="mt-1 text-xs text-text-secondary">
          Условие старта: «−50% первые 30 дней или до первых 50 оплат» — акция выключается
          автоматически, как только сработает любое из условий.
          {promo?.note ? ` Сейчас: ${promo.note}` : ""}
        </p>

        {promo ? (
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-text-secondary">
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={promo.active && promo.percent > 0}
                onChange={(e) => void savePromo({ enabled: e.target.checked })}
              />
              включена
            </label>
            <label className="flex items-center gap-1.5">
              скидка, %:
              <input
                type="number"
                min={0}
                max={90}
                value={promoPercent ?? promo.percent}
                onChange={(e) => setPromoPercent(Number(e.target.value))}
                className={`${field} w-16`}
              />
            </label>
            <label className="flex items-center gap-1.5">
              лимит оплат:
              <input
                type="number"
                min={0}
                value={promoLimit ?? promo.max_paid ?? 0}
                onChange={(e) => setPromoLimit(Number(e.target.value))}
                className={`${field} w-20`}
              />
            </label>
            <label className="flex items-center gap-1.5">
              до (UTC):
              <input
                type="datetime-local"
                value={promoEnds}
                onChange={(e) => setPromoEnds(e.target.value)}
                className={field}
              />
            </label>
            <span className="font-mono text-[11px] text-text-muted">
              конец: {when(promo.ends_at)} · оплачено: {promo.paid}
            </span>
            <button
              type="button"
              onClick={() =>
                void savePromo({
                  percent: promoPercent ?? promo.percent,
                  max_paid: promoLimit ?? promo.max_paid ?? 0,
                  ...(promoEnds ? { ends_at: new Date(promoEnds).toISOString() } : {}),
                })
              }
              disabled={busy}
              className="btn-primary px-3 py-1.5 text-xs"
            >
              Сохранить акцию
            </button>
          </div>
        ) : null}
      </div>

      {/* Ручная выдача тарифа */}
      <div className="rounded border border-line bg-ink-secondary p-4">
        <h3 className="text-sm font-semibold">Выдать тариф вручную</h3>
        <p className="mt-1 text-xs text-text-secondary">
          Для оплат вне бота, подарков и компенсаций: премиум продлевается от текущего
          срока, а в журнал попадает строка с пометкой «ручная выдача».
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-text-secondary">
          <label className="flex items-center gap-1.5">
            id аккаунта:
            <input
              value={grantUser}
              onChange={(e) => setGrantUser(e.target.value)}
              placeholder="17"
              className={`${field} w-24`}
            />
          </label>
          <label className="flex items-center gap-1.5">
            тариф:
            <select value={grantPlan} onChange={(e) => setGrantPlan(e.target.value)} className={field}>
              {plans.map((plan) => (
                <option key={plan.code} value={plan.code}>
                  {plan.title}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1.5">
            скидка, %:
            <input
              type="number"
              min={0}
              max={90}
              value={grantPercent}
              onChange={(e) => setGrantPercent(Number(e.target.value))}
              className={`${field} w-16`}
            />
          </label>
          <button
            type="button"
            onClick={() => void grant()}
            disabled={busy}
            className="btn-primary px-3 py-1.5 text-xs"
          >
            Выдать
          </button>
        </div>
      </div>

      {/* Журнал оплат */}
      <div className="rounded border border-line bg-ink-secondary p-4">
        <h3 className="text-sm font-semibold">Журнал оплат</h3>
        <div className="mt-3 flex flex-col gap-2">
          {(payments ?? []).map((item) => (
            <div
              key={item.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded border border-line bg-ink-tertiary p-2 text-xs"
            >
              <span className="font-mono text-[11px] text-text-muted">#{item.id}</span>
              <span className="font-semibold">{item.plan_code}</span>
              <span className="text-text-secondary">{rub(item.amount_rub)}</span>
              {item.discount_percent ? (
                <span className="text-accent-secondary">−{item.discount_percent}%</span>
              ) : null}
              <span className="text-text-secondary">{item.days} дн.</span>
              <span className="font-mono text-[11px] text-text-muted">{item.provider}</span>
              <span className={item.status === "paid" ? "text-accent-secondary" : "text-text-muted"}>
                {item.status}
              </span>
              {item.user_id ? <span className="text-text-muted">аккаунт {item.user_id}</span> : null}
              <span className="font-mono text-[11px] text-text-muted">{when(item.created_at)}</span>
            </div>
          ))}
          {payments && payments.length === 0 ? (
            <p className="text-xs text-text-muted">
              Оплат пока нет. Первые продажи появятся здесь, когда подключим CryptoBot;
              ручные выдачи видны сразу.
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

