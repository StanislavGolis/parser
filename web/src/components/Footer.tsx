import Link from "next/link";

export default function Footer() {
  return (
    <footer className="mt-16 border-t border-neutral-800">
      <div className="container-site flex flex-col items-center justify-between gap-3 py-6 text-xs text-neutral-500 sm:flex-row">
        <p>© {new Date().getFullYear()} Галерея — автоматический архив медиа с имиджборд.</p>
        <nav className="flex gap-4">
          <Link href="/" className="hover:text-neutral-300">Новинки</Link>
          <Link href="/top" className="hover:text-neutral-300">Популярное</Link>
        </nav>
      </div>
    </footer>
  );
}
