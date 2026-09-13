// Микроразметка schema.org (JSON-LD): «хлебные крошки» и безопасная вставка в HTML.

import { SITE_URL } from "@/lib/env";

/** Элемент «хлебных крошек»: имя и путь на сайте. */
export interface Crumb {
  name: string;
  path: string;
}

function absolute(path: string): string {
  return `${SITE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

/**
 * BreadcrumbList для страницы (главная → разделы → раздел → файл).
 * Позиции нумеруются с 1: так поисковик строит цепочку навигации.
 */
export function breadcrumbList(crumbs: Crumb[]) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: crumbs.map((crumb, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: crumb.name,
      item: absolute(crumb.path),
    })),
  };
}

/**
 * JSON-LD для вставки через `dangerouslySetInnerHTML`: экранируем «<»,
 * чтобы из данных нельзя было вставить HTML-тег.
 */
export function jsonLdHtml(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
