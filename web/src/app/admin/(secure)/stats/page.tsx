import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Статистика" };

/** Что появится на этой вкладке (план этапа P1 — «Посещаемость и поведение»). */
const PLANNED = [
  "Посетители и сессии: день / неделя / месяц, новые vs вернувшиеся",
  "Топ страниц и переходов, источники (referrer, UTM), устройства и браузеры",
  "Поведение: глубина просмотра, клики по баннеру «новое с визита», фильтры, открытия лайтбокса",
  "Воронки: лендинг → файл → скачивание, регистрация → премиум",
  "Топ разделов и файлов, активность по часам, здоровье API (429/5xx)",
  "Сводный отчёт по трафику из логов nginx (GoAccess) рядом с нашими метриками",
];

export default function AdminStatsPage() {
  return (
    <div>
      <h2 className="text-xl font-bold">Статистика посещаемости</h2>
      <p className="mt-1 text-sm text-text-secondary">
        Вкладка в разработке. Сейчас в базе есть только статистика по файлам (просмотры и
        скачивания с IP-хешем) — её видно на вкладке{" "}
        <Link href="/admin/content" className="text-accent-primary hover:underline">
          «Контент»
        </Link>
        .
      </p>

      <ul className="mt-5 flex flex-col gap-2">
        {PLANNED.map((item) => (
          <li
            key={item}
            className="rounded border border-line bg-ink-secondary/40 px-3 py-2 text-sm text-text-secondary"
          >
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
