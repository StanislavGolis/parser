"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiPatch, apiPost, apiSend } from "@/lib/api";
import { useAdminToken } from "@/lib/adminAuth";
import { formatNumber, parseUtc } from "@/lib/format";
import type { AdminPlan, AdminPlans, PaymentItem, PromoItem } from "@/lib/types";

const PLAN_ORDER = ["days3", "month", "year", "forever"];

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
  const [promoDraft, setPromoDraft] = useState<Record<number, Partial<PromoItem>>>({});
  const [newPromo, setNewPromo] = useState({
    title: "",
    description: "",
    percent: 20,
    ends_at: "",
    max_paid: 0,
    applies_to: "",
  });
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

  async function createPromo() {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await apiPost<PromoItem>(
        "/api/v1/admin/plans/promos",
        {
          title: newPromo.title.trim() || "Акция",
          description: newPromo.description.trim(),
          percent: newPromo.percent,
          max_paid: newPromo.max_paid || null,
          applies_to: newPromo.applies_to
            .split(",")
            .map((code) => code.trim())
            .filter(Boolean),
          ...(newPromo.ends_at ? { ends_at: new Date(newPromo.ends_at).toISOString() } : {}),
        },
        token,
      );
      setNewPromo({ title: "", description: "", percent: 20, ends_at: "", max_paid: 0, applies_to: "" });
      await load(token);
    } catch (err) {
      guard(err);
    } finally {
      setBusy(false);
    }
  }

  async function patchPromo(id: number, patch: Record<string, unknown>) {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await apiPatch<PromoItem>(`/api/v1/admin/plans/promos/${id}`, patch, token);
      setPromoDraft((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      await load(token);
    } catch (err) {
      guard(err);
    } finally {
      setBusy(false);
    }
  }

  async function deletePromo(id: number, title: string) {
    if (!token || !window.confirm(`Удалить акцию «${title}»?`)) return;
    setBusy(true);
    setError(null);
    try {
      await apiSend<{ ok: boolean }>(`/api/v1/admin/plans/promos/${id}`, {
        method: "DELETE",
        token,
      });
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

  const promos = data?.promos ?? [];
  const activePromos = promos.filter((item) => item.active);
  /** Скидка для тарифа: самая выгодная из активных акций, применимых к нему. */
  function discountFor(code: string): number {
    const list = activePromos.filter(
      (item) => !item.applies_to.length || item.applies_to.includes(code),
    );
    return list.length ? Math.max(...list.map((item) => item.percent)) : 0;
  }
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
          Free видит открытые разделы. Premium открывает приватные разделы, оригиналы
          и скачивание. Витрина продаёт за звёзды Telegram: рублёвая цена
          хранится справочно — для журнала и учёта, покупатель её не видит.
        </p>

        <div className="mt-3 flex flex-col gap-2">
          {plans.map((plan) => {
            const edit = draft[plan.code] ?? {};
            const price = edit.price_rub ?? plan.price_rub;
            const days = edit.days ?? plan.days;
            const active = edit.is_active ?? plan.is_active;
            const promoPercent = discountFor(plan.code);
            const now = Math.max(1, Math.round((price * (100 - promoPercent)) / 100));
            const dirty = Object.keys(edit).length > 0;
            return (
              <div key={plan.code} className="rounded border border-line bg-ink-tertiary p-3">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-text-secondary">
                  <span className="font-semibold text-text-primary">{plan.title}</span>
                  <span className="font-mono text-[11px] text-text-muted">{plan.code}</span>
                  <label className="flex items-center gap-1.5" title="Цена в звёздах Telegram — её видит покупатель">
                    цена, ⭐:
                    <input
                      type="number"
                      min={0}
                      value={edit.price_stars ?? plan.price_stars ?? 0}
                      onChange={(e) => patchPlan(plan.code, { price_stars: Number(e.target.value) })}
                      className={`${field} w-20`}
                    />
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
                  <label className="flex items-center gap-1.5" title="Справочная цена в рублях: журнал и учёт, покупателю не показывается">
                    ₽ (справочно):
                    <input
                      type="number"
                      min={0}
                      value={price}
                      onChange={(e) => patchPlan(plan.code, { price_rub: Number(e.target.value) })}
                      className={`${field} w-24`}
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

      {/* Акции: список + создание; включаются вручную под событие */}
      <div className="rounded border border-line bg-ink-secondary p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Акции</h3>
          <span className="text-xs text-text-muted">
            {data
              ? `всего: ${promos.length} · активных: ${activePromos.length}`
              : "загрузка…"}
          </span>
        </div>
        <p className="mt-1 text-xs text-text-secondary">
          Акции можно готовить заранее и включать под событие: у каждой своё название,
          описание, процент, срок и лимит оплат. Витрина и бот берут самую выгодную
          активную акцию для каждого тарифа.
        </p>

        <div className="mt-3 flex flex-col gap-2">
          {promos.map((item) => {
            const edit = promoDraft[item.id] ?? {};
            const title = edit.title ?? item.title;
            const description = edit.description ?? item.description;
            const percent = edit.percent ?? item.percent;
            const maxPaid = edit.max_paid ?? item.max_paid ?? 0;
            const applies = (edit.applies_to ?? item.applies_to).join(", ");
            const dirty = Object.keys(edit).length > 0;
            return (
              <div
                key={item.id}
                className={`rounded border p-3 ${
                  item.active ? "border-accent-secondary/50 bg-ink-tertiary" : "border-line bg-ink-tertiary"
                }`}
              >
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-text-secondary">
                  <input
                    value={title}
                    placeholder="Название акции"
                    onChange={(e) =>
                      setPromoDraft((prev) => ({ ...prev, [item.id]: { ...prev[item.id], title: e.target.value } }))
                    }
                    className={`${field} w-52`}
                  />
                  <label className="flex items-center gap-1.5">
                    скидка, %:
                    <input
                      type="number"
                      min={0}
                      max={90}
                      value={percent}
                      onChange={(e) =>
                        setPromoDraft((prev) => ({ ...prev, [item.id]: { ...prev[item.id], percent: Number(e.target.value) } }))
                      }
                      className={`${field} w-16`}
                    />
                  </label>
                  <label className="flex items-center gap-1.5">
                    лимит оплат:
                    <input
                      type="number"
                      min={0}
                      value={maxPaid}
                      onChange={(e) =>
                        setPromoDraft((prev) => ({ ...prev, [item.id]: { ...prev[item.id], max_paid: Number(e.target.value) } }))
                      }
                      className={`${field} w-20`}
                    />
                  </label>
                  <label className="flex items-center gap-1.5" title="Список кодов тарифов через запятую; пусто — на все">
                    тарифы:
                    <input
                      value={applies}
                      placeholder="все"
                      onChange={(e) =>
                        setPromoDraft((prev) => ({
                          ...prev,
                          [item.id]: {
                            ...prev[item.id],
                            applies_to: e.target.value.split(",").map((code) => code.trim()).filter(Boolean),
                          },
                        }))
                      }
                      className={`${field} w-36`}
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => void patchPromo(item.id, { is_active: !item.is_active })}
                    disabled={busy}
                    className={item.is_active ? "btn-ghost px-3 py-1.5 text-xs" : "btn-primary px-3 py-1.5 text-xs"}
                  >
                    {item.is_active ? "Выключить" : "Включить"}
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      void patchPromo(item.id, {
                        title,
                        description,
                        percent,
                        max_paid: maxPaid,
                        applies_to: edit.applies_to ?? item.applies_to,
                      })
                    }
                    disabled={busy || !dirty}
                    className={dirty ? "btn-primary px-3 py-1.5 text-xs" : "btn-ghost px-3 py-1.5 text-xs"}
                  >
                    Сохранить
                  </button>
                  <button
                    type="button"
                    onClick={() => void deletePromo(item.id, item.title)}
                    disabled={busy}
                    className="text-text-muted hover:text-accent-danger"
                  >
                    удалить
                  </button>
                  <span className={item.active ? "text-accent-secondary" : "text-text-muted"}>
                    {item.active ? `идёт: −${item.percent}%` : `не активна: ${item.reason || "—"}`}
                  </span>
                  <span className="font-mono text-[11px] text-text-muted">
                    до {when(item.ends_at)} · оплат осталось: {item.paid_left ?? "∞"}
                  </span>
                </div>
                <input
                  value={description}
                  placeholder="Описание для витрины — его увидят в боте"
                  onChange={(e) =>
                    setPromoDraft((prev) => ({ ...prev, [item.id]: { ...prev[item.id], description: e.target.value } }))
                  }
                  className={`${field} mt-2 w-full`}
                />
              </div>
            );
          })}
          {promos.length === 0 ? (
            <p className="text-xs text-text-muted">
              Акций пока нет — заведите первую ниже. Она создаётся выключенной.
            </p>
          ) : null}
        </div>

        {/* Новая акция: заводим заранее, включаем кнопкой у готовой */}
        <div className="mt-4 border-t border-line pt-3">
          <h4 className="text-xs font-semibold text-text-primary">Новая акция</h4>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-text-secondary">
            <input
              value={newPromo.title}
              placeholder="Название (видно покупателю)"
              onChange={(e) => setNewPromo((prev) => ({ ...prev, title: e.target.value }))}
              className={`${field} w-52`}
            />
            <input
              value={newPromo.description}
              placeholder="Описание для витрины"
              onChange={(e) => setNewPromo((prev) => ({ ...prev, description: e.target.value }))}
              className={`${field} w-64`}
            />
            <label className="flex items-center gap-1.5">
              скидка, %:
              <input
                type="number"
                min={0}
                max={90}
                value={newPromo.percent}
                onChange={(e) => setNewPromo((prev) => ({ ...prev, percent: Number(e.target.value) }))}
                className={`${field} w-16`}
              />
            </label>
            <label className="flex items-center gap-1.5">
              лимит оплат:
              <input
                type="number"
                min={0}
                value={newPromo.max_paid}
                onChange={(e) => setNewPromo((prev) => ({ ...prev, max_paid: Number(e.target.value) }))}
                className={`${field} w-20`}
              />
            </label>
            <label className="flex items-center gap-1.5" title="Коды тарифов через запятую (week, month, year, forever); пусто — на все">
              тарифы:
              <input
                value={newPromo.applies_to}
                placeholder="все"
                onChange={(e) => setNewPromo((prev) => ({ ...prev, applies_to: e.target.value }))}
                className={`${field} w-32`}
              />
            </label>
            <label className="flex items-center gap-1.5">
              до (UTC):
              <input
                type="datetime-local"
                value={newPromo.ends_at}
                onChange={(e) => setNewPromo((prev) => ({ ...prev, ends_at: e.target.value }))}
                className={field}
              />
            </label>
            <button
              type="button"
              onClick={() => void createPromo()}
              disabled={busy}
              className="btn-primary px-3 py-1.5 text-xs"
            >
              Создать акцию
            </button>
          </div>
          <p className="mt-1 text-[11px] text-text-muted">
            Акция создаётся выключенной: подготовьте условия заранее и нажмите «Включить»,
            когда придёт событие. Скидка применяется и к рублям, и к звёздам.
          </p>
        </div>
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

