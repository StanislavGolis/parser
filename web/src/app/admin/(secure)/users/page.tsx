import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Пользователи" };

/** Что появится на этой вкладке (план этапа P2 — «Управление пользователями»). */
const PLANNED = [
  "Список аккаунтов: email, дата регистрации, активен/заблокирован, премиум до, меток, просмотров, скачиваний, последний вход",
  "Поиск по email, сортировка и пагинация, выгрузка CSV",
  "Карточка пользователя: сессии (время, IP-хеш, браузер), метки, скачивания, история премиума",
  "Действия: выдать/снять премиум (на N дней или бессрочно), заблокировать, сбросить пароль письмом, выйти со всех устройств, удалить аккаунт",
  "Аудит действий админов: кто, что и когда менял",
];

export default function AdminUsersPage() {
  return (
    <div>
      <h2 className="text-xl font-bold">Управление пользователями</h2>
      <p className="mt-1 text-sm text-text-secondary">
        Вкладка в разработке. Данные уже есть в базе (`users`, `sessions`, `media_marks`), нужны
        миграция для следа сессий и админские эндпоинты.
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

      <p className="mt-6 text-xs text-text-muted">
        Пока управлять премиумом можно через БД или{" "}
        <Link href="/admin/content" className="text-accent-primary hover:underline">
          вкладку «Контент»
        </Link>
        .
      </p>
    </div>
  );
}
