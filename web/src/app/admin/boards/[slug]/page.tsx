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
    <div className="container-site max-w-6xl py-6 sm:py-8">
      <Link
        href="/admin"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-neutral-400 transition-colors hover:text-white"
      >
        <ArrowLeftIcon className="h-4 w-4" />
        К списку разделов
      </Link>
      <h2 className="text-xl font-bold">Треды раздела /{slug}</h2>
      <p className="mt-1 text-sm text-neutral-500">
        Управление тредами: что парсить, что показывать публично и что открывать по коду.
      </p>
      <div className="mt-5">
        <AdminBoardThreads slug={slug} />
      </div>
    </div>
  );
}
