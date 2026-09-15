import type { Metadata } from "next";
import Link from "next/link";

import { DMCA_EMAIL, SUPPORT_EMAIL } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Правила пользования",
  robots: { index: false, follow: false },
};

/** Правила пользования сервисом (ToS). Тексты — черновик, требуют юридической вычитки. */
export default function TosPage() {
  return (
    <article className="container-site max-w-3xl py-8 text-sm leading-relaxed text-text-secondary">
      <h1 className="text-2xl font-bold text-text-primary">Правила пользования</h1>
      <p className="mt-2 font-mono text-[11px] uppercase tracking-widest text-text-muted">
        редакция от 14.09.2026
      </p>

      <h2 className="mt-6 text-base font-semibold text-text-primary">1. Что это за сервис</h2>
      <p className="mt-2">
        Dredger — закрытый архив медиафайлов, доступный только авторизованным
        пользователям. Сервис собирает и упорядочивает файлы из открытых источников,
        хранит их и выдаёт по подписке. Регистрация свободная, доступ к контенту —
        по правилам подписки.
      </p>

      <h2 className="mt-6 text-base font-semibold text-text-primary">2. Возраст</h2>
      <p className="mt-2">
        Сервис содержит материалы для взрослых. Пользоваться им можно только с 18 лет.
        Регистрируясь, вы подтверждаете, что достигли этого возраста.
      </p>

      <h2 className="mt-6 text-base font-semibold text-text-primary">3. Аккаунт</h2>
      <ul className="mt-2 list-disc pl-5">
        <li>аккаунт личный, передавать его третьим лицам нельзя;</li>
        <li>доступ привязан к Telegram или email — не публикуйте ссылки входа;</li>
        <li>при подозрении на взлом напишите в поддержку: {SUPPORT_EMAIL}.</li>
      </ul>

      <h2 className="mt-6 text-base font-semibold text-text-primary">4. Что запрещено</h2>
      <ul className="mt-2 list-disc pl-5">
        <li>любые материалы с несовершеннолетними — доступ закрывается немедленно, хеш попадает в блок-лист;</li>
        <li>контент, нарушающий закон, и материалы, связанные с насилием или преследованием людей;</li>
        <li>массовая автоматическая выкачка файлов (парсеры, скрипты) без письменного согласия;</li>
        <li>коммерческое распространение файлов архива и выдача их за свои.</li>
      </ul>

      <h2 className="mt-6 text-base font-semibold text-text-primary">5. Контент правообладателей</h2>
      <p className="mt-2">
        Мы уважаем права авторов и не претендуем на присылаемые материалы. Если ваш файл
        опубликован без разрешения — подайте требование:{" "}
        <Link href="/dmca" className="text-accent-primary hover:underline">
          страница DMCA
        </Link>{" "}
        ({DMCA_EMAIL}). Мы скрываем файл и его тред и рассматриваем обращения в первую очередь.
      </p>

      <h2 className="mt-6 text-base font-semibold text-text-primary">6. Ответственность</h2>
      <p className="mt-2">
        Сервис предоставляется «как есть»: возможны перерывы в работе, ошибки и пропажа
        отдельных файлов. Мы не отвечаем за содержание материалов из открытых источников
        и за использование вами скачанных файлов.
      </p>

      <h2 className="mt-6 text-base font-semibold text-text-primary">7. Изменения</h2>
      <p className="mt-2">
        Правила могут обновляться — актуальная редакция всегда на этой странице. Существенные
        изменения анонсируем в боте.
      </p>

      <p className="mt-6 text-xs text-text-muted">
        Вопросы и претензии: {SUPPORT_EMAIL} · требования правообладателей: {DMCA_EMAIL}
      </p>
    </article>
  );
}
