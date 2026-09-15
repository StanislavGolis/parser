"use client";

import { useEffect, useState } from "react";

import { apiGet } from "@/lib/api";
import { TELEGRAM_BOT_URL } from "@/lib/env";
import type { PlanPrice, PlansView } from "@/lib/types";

/**
 * Тарифная сетка на сайте: цены только в звёздах Telegram.
 *
 * Почему клиентский компонент. Сайт работает в закрытом режиме, а серверный
 * рендер не имеет cookie сессии — SSR-запрос к API вернул бы 401. Здесь запрос
 * идёт из браузера, поэтому витрину видит именно вошедший пользователь.
 *
 * Мобильная версия: карточки в одну колонку, крупные тап-зоны, никаких таблиц —
 * тот же компонент, только сетка меняется на `sm:grid-cols-2 lg:grid-cols-4`.
 */
export default function PricingGrid() {
  const [data, setData] = useState<PlansView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    apiGet<PlansView>("/api/v1/plans")
      .then((result) => {
        if (alive) setData(result);
      })
      .catch(() => {
        if (alive) setError("Не удалось загрузить тарифы. Обновите страницу.");
      });
    return () => {
      alive = false;
    };
  }, []);

  const plans = (data?.plans ?? []).filter((plan) => plan.stars_now || plan.price_stars);
  const promos = (data?.promos ?? []).filter((promo) => promo.active);

  if (error) {
    return <p className="mt-6 text-sm text-accent-danger">{error}</p>;
  }

  if (!data) {
    return (
      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((key) => (
          <div key={key} className="h-40 animate-pulse rounded border border-line bg-ink-secondary" />
        ))}
      </div>
    );
  }

  return (
    <div className="mt-6">
      {/* Акции: название и описание задаются в админке */}
      {promos.map((promo) => (
        <div
          key={promo.id}
          className="mb-4 rounded border border-accent-secondary/50 bg-ink-secondary p-3"
        >
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-text-primary">
            <span className="font-semibold">{promo.title}</span>
            <span className="badge badge-ok shrink-0">−{promo.percent}%</span>
            {promo.days_left !== null ? (
              <span className="font-mono text-[11px] text-text-muted">
                осталось {promo.days_left} дн.
              </span>
            ) : null}
            {promo.paid_left !== null ? (
              <span className="font-mono text-[11px] text-text-muted">
                · {promo.paid_left} оплат
              </span>
            ) : null}
          </p>
          {promo.description ? (
            <p className="mt-1 text-xs text-text-secondary">{promo.description}</p>
          ) : null}
        </div>
      ))}

      {plans.length === 0 ? (
        <p className="text-sm text-text-secondary">
          Тарифы временно недоступны — загляните чуть позже.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {plans.map((plan) => (
            <PlanCard key={plan.code} plan={plan} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Карточка тарифа: цена в звёздах, срок и кнопка «оплатить в боте». */
function PlanCard({ plan }: { plan: PlanPrice }) {
  const stars = plan.stars_now ?? plan.price_stars ?? 0;
  const base = plan.price_stars ?? 0;
  const discount = base > stars;

  function days(): string {
    if (plan.is_forever) return "без срока";
    if (plan.days >= 30 && plan.days % 30 === 0) return `${plan.days / 30} мес.`;
    return `${plan.days} дн.`;
  }

  return (
    <div
      className={`flex flex-col rounded border p-4 ${
        plan.badge ? "border-accent-primary/50 bg-ink-secondary" : "border-line bg-ink-secondary"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-semibold text-text-primary">{plan.title}</span>
        {plan.badge ? (
          <span className="badge badge-ok shrink-0">{plan.badge}</span>
        ) : null}
      </div>
      <p className="mt-1 font-mono text-[11px] uppercase tracking-widest text-text-muted">
        {days()}
      </p>

      <p className="mt-3 flex flex-wrap items-baseline gap-x-2">
        <span className="font-mono text-2xl text-text-primary">{stars}</span>
        <span className="text-sm text-text-secondary">⭐</span>
        {discount ? (
          <span className="font-mono text-xs text-text-muted line-through">{base} ⭐</span>
        ) : null}
      </p>

      {plan.description ? (
        <p className="mt-2 text-xs text-text-secondary">{plan.description}</p>
      ) : null}

      <a
        href={TELEGRAM_BOT_URL || "#"}
        target="_blank"
        rel="noreferrer"
        className="btn-primary mt-4 block text-center text-sm"
      >
        Оплатить в боте
      </a>
    </div>
  );
}
