import Link from "next/link";

export default function NotFound() {
  return (
    <div className="container-site flex flex-col items-center justify-center gap-4 py-24 text-center">
      <p className="text-6xl font-black text-neutral-800">404</p>
      <h1 className="text-xl font-semibold">Ничего не нашлось</h1>
      <p className="max-w-md text-sm text-neutral-500">
        Такой страницы или файла нет, либо он ещё не был разобран парсером.
      </p>
      <Link href="/" className="btn-primary mt-2">
        На главную
      </Link>
    </div>
  );
}
