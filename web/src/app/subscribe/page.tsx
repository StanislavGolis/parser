import type { Metadata } from "next";
import Link from "next/link";

import PricingGrid from "@/components/PricingGrid";

export const metadata: Metadata = { title: "Подписка" };

const INCLUDED = [
  {
    title: "Открытые разделы",
    body: "Смотреть можно без подписки — превью открытого архива доступны всем вошедшим.",
    free: true,
  },
  {
    title: "Приватные разделы",
    body: "Закрытые разделы и темы открываются по подписке — размытое превью видно без неё.",
    free: false,
  },
  {
    title: "Скачивание и оригиналы",
    body: "Скачивание файлов и оригиналы доступны только по подписке.",
    free: false,
  },
  {
    title: "Без рекламы",
    body: "Подписчикам реклама не показывается.",
    free: false,
  },
];

const STEPS = [
  "Нажмите «Оплатить в боте» — откроется наш Telegram-бот на нужном тарифе.",
  "Бот выставит счёт в звёздах Telegram (⭐) — оплата проходит в Telegram, без карт и банков.",
  "Подписка включится сразу после оплаты: вернитесь на сайт по ссылке из бота.",
];

/**
 * Страница тарифов: витрина в звёздах + объяснение, что входит в подписку.
 *
 * Держим её простой: одна сетка тарифов (3 дня / месяц / год / навсегда),
 * блок «что входит», три шага оплаты и короткие ответы на частые вопросы.
 */
export default function SubscribePage() {
  return (
    <div className="container-site max-w-4xl py-8 sm:py-10">
      <h1 className="text-xl font-bold text-text-primary">Подписка</h1>
      <p className="mt-1 text-sm text-text-secondary">
        Архив открыт для просмотра, а приватные разделы, скачивание и оригиналы —
        по подписке. Оплата в звёздах Telegram: быстро и без рекламы на сайте.
      </p>

      <PricingGrid />

      {/* Что входит */}
      <h2 className="mt-10 text-base font-semibold text-text-primary">Что входит</h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {INCLUDED.map((item) => (
          <div key={item.title} className="rounded border border-line bg-ink-secondary p-4">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-text-primary">{item.title}</span>
              <span className={`badge shrink-0 ${item.free ? "badge-ok" : "badge-warn"}`}>
                {item.free ? "бесплатно" : "по подписке"}
              </span>
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-text-secondary">{item.body}</p>
          </div>
        ))}
      </div>

      {/* Как оплатить */}
      <h2 className="mt-10 text-base font-semibold text-text-primary">Как оплатить</h2>
      <ol className="mt-3 flex flex-col gap-2">
        {STEPS.map((step, index) => (
          <li
            key={step}
            className="flex gap-3 rounded border border-line bg-ink-secondary px-4 py-3 text-sm text-text-secondary"
          >
            <span className="font-mono text-xs text-accent-primary">{index + 1}</span>
            <span>{step}</span>
          </li>
        ))}
      </ol>

      <h2 className="mt-10 text-base font-semibold text-text-primary">Частые вопросы</h2>
      <dl className="mt-3 flex flex-col gap-3">
        <div className="rounded border border-line bg-ink-secondary p-4">
          <dt className="text-sm text-text-primary">Что будет, когда подписка закончится?</dt>
          <dd className="mt-1 text-xs text-text-secondary">
            Приватные разделы и скачивание снова закроются, открытые разделы останутся
            доступны. Файлы, которые вы смотрели, и закладки не пропадут.
          </dd>
        </div>
        <div className="rounded border border-line bg-ink-secondary p-4">
          <dt className="text-sm text-text-primary">Можно ли продлить подписку заранее?</dt>
          <dd className="mt-1 text-xs text-text-secondary">
            Да: новый срок прибавляется к текущему — прогресс оплаченного времени не теряется.
          </dd>
        </div>
        <div className="rounded border border-line bg-ink-secondary p-4">
          <dt className="text-sm text-text-primary">Что такое звёзды?</dt>
          <dd className="mt-1 text-xs text-text-secondary">
            Это внутренняя валюта Telegram (⭐). Оплата проходит в самом Telegram, карта
            не нужна, а подписка включается сразу после оплаты.
          </dd>
        </div>
        <div className="rounded border border-line bg-ink-secondary p-4">
          <dt className="text-sm text-text-primary">Сколько файлов можно скачать?</dt>
          <dd className="mt-1 text-xs text-text-secondary">
            Без ограничений по количеству: подписка открывает скачивание и оригиналы на срок
            тарифа.
          </dd>
        </div>
      </dl>

      <p className="mt-8 text-xs text-text-muted">
        <Link href="/" className="hover:text-text-secondary">
          ← Вернуться в архив
        </Link>
      </p>
    </div>
  );
}
