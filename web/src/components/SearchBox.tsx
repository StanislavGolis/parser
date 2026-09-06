"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { SearchIcon } from "@/components/icons";

/** Поле поиска: переход на /search?q=… */
export default function SearchBox({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  const router = useRouter();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const q = value.trim();
    if (q.length >= 2) router.push(`/search?q=${encodeURIComponent(q)}`);
  }

  return (
    <form onSubmit={submit} className="flex w-full max-w-xl items-center gap-2">
      <div className="relative flex-1">
        <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="имя файла, md5, sha-256…"
          className="input-sluice w-full pl-9"
          autoFocus
        />
      </div>
      <button type="submit" disabled={value.trim().length < 2} className="btn-primary">
        Поиск
      </button>
    </form>
  );
}
