"use client";

/** Компактный переключатель в стиле админки DREDGER. */
export function Switch({
  checked,
  onChange,
  label,
  title,
  disabled = false,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
  title?: string;
  /** Значение унаследовано/недоступно: клики игнорируются. */
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-disabled={disabled}
      title={title}
      onClick={disabled ? undefined : onChange}
      className={`inline-flex shrink-0 items-center gap-2 rounded border px-2.5 py-1.5 text-xs font-medium transition-colors ${
        disabled ? "cursor-not-allowed opacity-60" : ""
      } ${
        checked
          ? "border-accent-primary/50 bg-accent-primary/15 text-accent-primary"
          : "border-line bg-ink-tertiary text-text-secondary hover:text-text-primary"
      }`}
    >
      <span className={`h-2 w-2 rounded-full ${checked ? "bg-amber-400" : "bg-neutral-600"}`} />
      {label}
    </button>
  );
}

export default Switch;
