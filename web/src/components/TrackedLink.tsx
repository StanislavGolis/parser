"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { trackEvent } from "@/lib/track";

/**
 * Ссылка, которая отмечает клик событием в своей аналитике.
 * Нужна для серверных компонентов: там onClick не повесить.
 */
export default function TrackedLink({
  href,
  event,
  className,
  children,
}: {
  href: string;
  event: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link href={href} className={className} onClick={() => trackEvent(event)}>
      {children}
    </Link>
  );
}
