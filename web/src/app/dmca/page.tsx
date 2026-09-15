import type { Metadata } from "next";
import Link from "next/link";

import { DMCA_EMAIL, DMCA_RESPONSE_HOURS, SUPPORT_EMAIL } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Правообладателям (DMCA)",
  robots: { index: false, follow: false },
};

/** Требования правообладателей: как подать и что происходит дальше. */
export default function DmcaPage() {
  return (
    <article className="container-site max-w-3xl py-8 text-sm leading-relaxed text-text-secondary">
      <h1 className="text-2xl font-bold text-text-primary">Правообладателям (DMCA)</h1>
      <p className="mt-2 font-mono text-[11px] uppercase tracking-widest text-text-muted">
        удаление контента — в течение {DMCA_RESPONSE_HOURS} часов
      </p>

      <h2 className="mt-6 text-base font-semibold text-text-primary">Как подать требование</h2>
      <p className="mt-2">
        Напишите на{" "}
        <a href={`mailto:${DMCA_EMAIL}`} className="text-accent-primary hover:underline">
          {DMCA_EMAIL}
        </a>{" "}
        и укажите:
      </p>
      <ul className="mt-2 list-disc pl-5">
        <li>кто вы и как с вами связаться (email, при необходимости — телефон);</li>
        <li>какой материал нарушает ваши права: ссылки на файл или страницы архива;</li>
        <li>подтверждение прав: авторство, договор, регистрация товарного знака и т.п.;</li>
        <li>заявление о добросовестности: «считаю использование неправомерным».</li>
      </ul>
      <p className="mt-2">
        Если ссылок нет — опишите материал словами (дата, раздел, тред): мы найдём файл
        сами.
      </p>

      <h2 className="mt-6 text-base font-semibold text-text-primary">Что мы делаем</h2>
      <ul className="mt-2 list-disc pl-5">
        <li>
          скрываем файл и весь тред — сразу, до окончания спора; при необходимости удаляем
          объект из хранилища;
        </li>
        <li>
          при подтверждении требования добавляем SHA-256 файла в блок-лист: повторное
          скачивание и импорт из архива файл не вернут;
        </li>
        <li>отвечаем на письмо: принято, скрыто, удалено или запрошены уточнения;</li>
        <li>
          ведём журнал действий модерации (кто и когда скрыл, что послужило причиной).
        </li>
      </ul>
      <p className="mt-2">
        Срок реакции — не более {DMCA_RESPONSE_HOURS} часов с момента получения письма.
        Если ответа нет дольше, напишите повторно: письмо могло попасть в спам.
      </p>

      <h2 className="mt-6 text-base font-semibold text-text-primary">Жалоба на файл с сайта</h2>
      <p className="mt-2">
        Быстрее всего — кнопка «Пожаловаться» в просмотре файла: жалоба сразу попадает в
        очередь модерации. Для материалов, связанных с безопасностью детей, доступ
        закрывается автоматически, без ожидания разбора.
      </p>

      <h2 className="mt-6 text-base font-semibold text-text-primary">Если требование ошибочно</h2>
      <p className="mt-2">
        Мы возвращаем контент, если выясняется, что права принадлежат другому лицу или
        использование разрешено. Повторные необоснованные требования разбираем отдельно.
      </p>

      <p className="mt-6 text-xs text-text-muted">
        Общие вопросы — {SUPPORT_EMAIL}; см. также{" "}
        <Link href="/tos" className="text-accent-primary hover:underline">
          правила пользования
        </Link>{" "}
        и{" "}
        <Link href="/privacy" className="text-accent-primary hover:underline">
          политику конфиденциальности
        </Link>
        .
      </p>
    </article>
  );
}
