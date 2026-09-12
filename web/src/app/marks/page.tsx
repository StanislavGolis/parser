import type { Metadata } from "next";
import Link from "next/link";

import Gallery from "@/components/Gallery";
import { ApiError } from "@/lib/api";
import { getBoards, getMarksPage } from "@/lib/data";
import { formatNumber } from "@/lib/format";
import type { MediaList } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Метки",
  // Личная страница: в поиске не нужна.
  robots: { index: false, follow: false },
};

const PER_PAGE = 30;

/** «Мои метки» — файлы, отмеченные пользователем (требует аккаунт). */
export default async function MarksPage() {
  let list: MediaList | null = null;
  try {
    list = await getMarksPage(1, PER_PAGE);
  } catch (err) {
    // 401 — не вошёл: показываем приглашение вместо списка
    if (!(err instanceof ApiError && err.status === 401)) throw err;
  }

  const boards = await getBoards();
  const boardsById = Object.fromEntries(boards.map((b) => [b.id, b]));

  return (
    <div className="py-2">
      <h1 className="dredge-title mb-1">
        метки // {list ? `${formatNumber(list.total)} файлов` : "мой список"}
      </h1>
      <p className="mb-4 font-mono text-[11px] text-text-muted">
        метка «отличный контент» поднимает файл в рейтинге и собирает здесь ваш личный список
      </p>

      {list ? (
        <Gallery
          initial={list}
          apiPath="/api/v1/marks"
          perPage={PER_PAGE}
          boardsById={boardsById}
          emptyTitle="Пока нет меток"
          emptyHint="Нажмите 🏷 на карточке или пробел в просмотре файла — он появится здесь."
        />
      ) : (
        <div className="flex flex-col items-center gap-3 rounded border border-dashed border-line py-16 text-center">
          <p className="font-mono text-xs uppercase tracking-widest text-text-muted">
            нужен аккаунт
          </p>
          <p className="max-w-md text-sm text-text-secondary">
            Метки доступны зарегистрированным пользователям. Войдите или создайте аккаунт —
            это займёт минуту.
          </p>
          <Link href="/login" className="btn-primary mt-1">
            Войти
          </Link>
        </div>
      )}
    </div>
  );
}
