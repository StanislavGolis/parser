import { ImageIcon } from "@/components/icons";

export default function EmptyState({
  title = "Пока пусто",
  hint = "Новые файлы появятся здесь после следующего прохода парсера.",
}: {
  title?: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded border border-dashed border-line py-20 text-center">
      <ImageIcon className="h-10 w-10 text-text-muted" />
      <div>
        <p className="font-medium text-text-primary">{title}</p>
        <p className="mt-1 text-sm text-text-secondary">{hint}</p>
      </div>
    </div>
  );
}
