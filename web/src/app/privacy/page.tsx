import type { Metadata } from "next";
import Link from "next/link";

import { DMCA_URL, FEEDBACK_URL } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Конфиденциальность",
  robots: { index: false, follow: false },
};

/** Политика конфиденциальности: какие данные собираем и зачем. */
export default function PrivacyPage() {
  return (
    <article className="container-site max-w-3xl py-8 text-sm leading-relaxed text-text-secondary">
      <h1 className="text-2xl font-bold text-text-primary">Политика конфиденциальности</h1>
      <p className="mt-2 font-mono text-[11px] uppercase tracking-widest text-text-muted">
        редакция от 14.09.2026
      </p>

      <h2 className="mt-6 text-base font-semibold text-text-primary">1. Какие данные мы храним</h2>
      <ul className="mt-2 list-disc pl-5">
        <li>
          аккаунт: Telegram ID и ник (или email), дата регистрации, срок подписки, статус
          администратора;
        </li>
        <li>сессии: случайный токен сессии и срок его жизни — чтобы не входить каждый раз;</li>
        <li>
          статистика: просмотры и скачивания файлов, заходы на страницы, отметки «нравится»
          и точка возврата («продолжить просмотр»);
        </li>
        <li>IP-адрес в виде необратимого хеша (SHA-256) — для защиты от накрутки и подбора;</li>
        <li>обращения и жалобы: текст, дата, кто отправил, к какому файлу относятся.</li>
      </ul>

      <h2 className="mt-6 text-base font-semibold text-text-primary">2. Зачем</h2>
      <ul className="mt-2 list-disc pl-5">
        <li>работа аккаунта и подписки: вход, сроки доступа, выдача доступа;</li>
        <li>работа сайта: показ просмотренных файлов, закладок, «продолжить просмотр»;</li>
        <li>безопасность: защита от автоматической выкачки и злоупотреблений;</li>
        <li>модерация: разбор жалоб и требований правообладателей.</li>
      </ul>

      <h2 className="mt-6 text-base font-semibold text-text-primary">3. Чего мы не делаем</h2>
      <ul className="mt-2 list-disc pl-5">
        <li>не продаём и не передаём данные третьим лицам для рекламы;</li>
        <li>не используем сторонние рекламные трекеры;</li>
        <li>не читаем содержимое ваших закладок и истории никому, кроме агрегатов статистики.</li>
      </ul>

      <h2 className="mt-6 text-base font-semibold text-text-primary">4. Cookies</h2>
      <p className="mt-2">
        Используем только необходимые cookies: сессия входа, технические отметки возраста
        и подсказок интерфейса. Отключение cookies сломает вход в аккаунт.
      </p>

      <h2 className="mt-6 text-base font-semibold text-text-primary">5. Сроки хранения</h2>
      <p className="mt-2">
        Данные аккаунта храним, пока аккаунт существует. Сессии истекают автоматически.
        Агрегированную статистику (без привязки к человеку) храним для отчётов. Жалобы и
        журнал модерации — как историю правомерности действий, в том числе после удаления
        аккаунта.
      </p>

      <h2 className="mt-6 text-base font-semibold text-text-primary">6. Ваши права</h2>
      <p className="mt-2">
        Вы можете запросить удаление аккаунта и связанных данных, а также копию данных о
        себе: отправьте запрос через{" "}
        <Link href={FEEDBACK_URL} className="text-accent-primary hover:underline">
          форму обратной связи
        </Link>
        . После удаления аккаунта доступ к архиву закрывается.
      </p>

      <h2 className="mt-6 text-base font-semibold text-text-primary">7. Обращения</h2>
      <p className="mt-2">
        Требования правообладателей разбираем через{" "}
        <Link href={DMCA_URL} className="text-accent-primary hover:underline">
          форму обратной связи
        </Link>{" "}
        (тема «Права и контент») — см.{" "}
        <Link href="/dmca" className="text-accent-primary hover:underline">
          страницу DMCA
        </Link>
        . Общие правила сервиса — в{" "}
        <Link href="/tos" className="text-accent-primary hover:underline">
          правилах пользования
        </Link>
        .
      </p>

      <p className="mt-6 text-xs text-text-muted">
        Мы можем обновлять политику: актуальная редакция всегда на этой странице.
      </p>
    </article>
  );
}
