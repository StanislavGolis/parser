import { ImageIcon } from "@/components/icons";

export default function EmptyState({
  title = "Пока пусто",
  hint = "Новые файлы появятся здесь после следующего прохода парсера.",
}: {
  title?: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-neutral-800 py-20 text-center">
      <ImageIcon className="h-10 w-10 text-neutral-700" />
      <div>
        <p className="font-medium text-neutral-300">{title}</p>
        <p className="mt-1 text-sm text-neutral-500">{hint}</p>
      </div>
    </div>
  );
}
