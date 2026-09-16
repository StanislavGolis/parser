import Link from "next/link";

import { DMCA_URL, FEEDBACK_URL } from "@/lib/legal";

export default function Footer() {
  return (
    <footer className="mt-12 border-t border-line">
      <div className="mx-auto flex w-full max-w-[1400px] flex-col items-center justify-between gap-3 px-4 py-6 sm:flex-row sm:px-6">
        <p className="font-mono text-[11px] text-text-muted">
          DREDGER — автоматический медиа-архив. 18+
        </p>
        <nav className="flex flex-wrap justify-center gap-x-5 gap-y-2 font-mono text-[11px] text-text-secondary" aria-label="Разделы в подвале">
          <Link href="/" className="transition-colors hover:text-text-primary">новое</Link>
          <Link href="/new" className="transition-colors hover:text-text-primary">весь поток</Link>
          <Link href="/boards" className="transition-colors hover:text-text-primary">разделы</Link>
          <Link href="/top" className="transition-colors hover:text-text-primary">популярное</Link>
          <Link href="/marks" className="transition-colors hover:text-text-primary">закладки</Link>
          <Link href="/feedback" className="transition-colors hover:text-text-primary">обратная связь</Link>
        </nav>
      </div>

      {/* Правовой блок: правила, порядок удаления контента и контакты.
          Эти страницы открыты и без входа — правообладателю нужно их прочитать. */}
      <div className="mx-auto flex w-full max-w-[1400px] flex-col items-center justify-between gap-2 border-t border-line/60 px-4 py-4 font-mono text-[10px] text-text-muted sm:flex-row sm:px-6">
        <nav className="flex flex-wrap justify-center gap-x-4 gap-y-1" aria-label="Правовая информация">
          <Link href="/tos" className="transition-colors hover:text-text-secondary">правила пользования</Link>
          <Link href="/dmca" className="transition-colors hover:text-text-secondary">правообладателям (DMCA)</Link>
          <Link href="/privacy" className="transition-colors hover:text-text-secondary">конфиденциальность</Link>
        </nav>
        <p>
          связь:{" "}
          <Link href={FEEDBACK_URL} className="transition-colors hover:text-text-secondary">
            форма обратной связи
          </Link>{" "}
          · контент:{" "}
          <Link href={DMCA_URL} className="transition-colors hover:text-text-secondary">
            правообладателям
          </Link>
        </p>
      </div>
    </footer>
  );
}
