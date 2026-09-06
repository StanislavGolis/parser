"use client";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="container-site flex flex-col items-center justify-center gap-4 py-24 text-center">
      <h1 className="text-xl font-semibold">Что-то пошло не так</h1>
      <p className="max-w-md text-sm text-neutral-500">
        Не удалось отобразить страницу{error?.digest ? ` (digest: ${error.digest})` : ""}. Попробуйте ещё раз
        или вернитесь позже.
      </p>
      <div className="mt-2 flex gap-3">
        <button type="button" onClick={() => reset()} className="btn-primary">
          Попробовать снова
        </button>
      </div>
    </div>
  );
}
