import Link from "next/link";

export default function Footer() {
  return (
    <footer className="mt-12 border-t border-line">
      <div className="mx-auto flex w-full max-w-[1400px] flex-col items-center justify-between gap-3 px-4 py-6 sm:flex-row sm:px-6">
        <p className="font-mono text-[11px] text-text-muted">
          DREDGE — автоматический медиа-архив с разделов.
        </p>
        <nav className="flex gap-5 font-mono text-[11px] text-text-secondary" aria-label="Разделы в подвале">
          <Link href="/" className="transition-colors hover:text-text-primary">доски</Link>
          <Link href="/new" className="transition-colors hover:text-text-primary">новинки</Link>
          <Link href="/top" className="transition-colors hover:text-text-primary">популярное</Link>
          <Link href="/favorites" className="transition-colors hover:text-text-primary">избранное</Link>
        </nav>
      </div>
    </footer>
  );
}
