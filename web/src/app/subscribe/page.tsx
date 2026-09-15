import type { Metadata } from "next";
import Link from "next/link";

import PricingGrid from "@/components/PricingGrid";
import SubscribeIncluded from "@/components/SubscribeIncluded";

export const metadata: Metadata = { title: "Подписка" };

const STEPS = [
  "«Оплатить в боте» — откроется бот на выбранном тарифе.",
  "Бот выставит счёт в звёздах Telegram: оплата проходит внутри Telegram.",
  "Подписка включается сразу — вернуться на сайт можно по ссылке из бота.",
];

const FAQ = [
  {
    q: "Если подписка закончится",
    a: "Закрытые разделы и скачивание закроются, открытые останутся доступны. Закладки сохранятся.",
  },
  {
    q: "Продление заранее",
    a: "Срок прибавляется к текущему: если до конца месяц, после оплаты будет два.",
  },
  {
    q: "Оплата не пришла",
    a: "Напишите боту — сверим журнал оплат и включим подписку вручную.",
  },
];

/**
 * Страница тарифов: витрина в звёздах + объяснение, что входит в подписку.
 *
 * Держим её простой: одна сетка тарифов (3 дня / месяц / год / навсегда),
 * блок «что входит», три шага оплаты и короткие ответы на частые вопросы.
 */
export default function SubscribePage() {
  return (
    <div className="container-site max-w-3xl py-8 sm:py-10">
      <h1 className="text-xl font-bold text-text-primary">Подписка</h1>
      <p className="mt-1 max-w-xl text-sm text-text-secondary">
        Закрытые разделы, оригиналы и скачивание — по подписке. Оплата звёздами
        Telegram: карта не нужна, автоплатежей нет.
      </p>

      <PricingGrid />

      {/* Что входит: конкретика с цифрами (сколько файлов и разделов) */}
      <h2 className="mt-10 text-base font-semibold text-text-primary">Что входит</h2>
      <SubscribeIncluded />

      {/* Как оплатить */}
      <h2 className="mt-10 text-base font-semibold text-text-primary">Как оплатить</h2>
      <ol className="mt-3 flex flex-col gap-2">
        {STEPS.map((step, index) => (
          <li key={step} className="flex gap-3 text-sm text-text-secondary">
            <span className="font-mono text-xs text-accent-primary">{index + 1}</span>
            <span>{step}</span>
          </li>
        ))}
      </ol>

      <h2 className="mt-10 text-base font-semibold text-text-primary">Частые вопросы</h2>
      <dl className="mt-3 flex flex-col gap-3">
        {FAQ.map((item) => (
          <div key={item.q}>
            <dt className="text-sm text-text-primary">{item.q}</dt>
            <dd className="mt-0.5 text-xs leading-relaxed text-text-secondary">{item.a}</dd>
          </div>
        ))}
      </dl>

      <p className="mt-8 text-xs text-text-muted">
        <Link href="/" className="hover:text-text-secondary">
          ← Вернуться в архив
        </Link>
      </p>
    </div>
  );
}
