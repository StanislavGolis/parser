import { SpinnerIcon } from "@/components/icons";

export default function Loading() {
  return (
    <div className="container-site flex min-h-64 items-center justify-center">
      <span className="inline-flex items-center gap-2 text-sm text-neutral-400">
        <SpinnerIcon className="h-5 w-5" />
        Загружаем…
      </span>
    </div>
  );
}
