import Link from "next/link";

import AdminBoardThreads from "@/components/AdminBoardThreads";
import { ArrowLeftIcon } from "@/components/icons";

export const metadata = {
  title: "Треды раздела",
  robots: { index: false, follow: false },
};

export default function AdminBoardThreadsPage({ params }: { params: { slug: string } }) {
  const { slug } = params;
  return (
    <div>
      <Link
        href="/admin/content"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-text-secondary transition-colors hover:text-text-primary"
      >
        <ArrowLeftIcon className="h-4 w-4" />
        К списку разделов
      </Link>
      <h2 className="text-xl font-bold">Треды раздела /{slug}</h2>
      <p className="mt-1 text-sm text-text-secondary">
        Управление тредами: что парсить, что показывать публично, что открывать по подписке —
        и удаление треда вместе с файлами.
      </p>
      <div className="mt-5">
        <AdminBoardThreads slug={slug} />
      </div>
    </div>
  );
}
