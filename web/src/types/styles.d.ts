/**
 * Декларации глобальных (не-CSS-module) файлов стилей.
 *
 * В типах Next.js 14 объявлены только CSS-модули ('*.module.css'),
 * а для обычного импорта вида `import "./globals.css"` декларации нет —
 * TypeScript может ругаться TS2307 («Cannot find module './globals.css'»),
 * если включён strict-режим проверки side-effect импортов или это делает
 * языковой сервер редактора. Данная декларация закрывает этот случай.
 */
declare module "*.css";
declare module "*.scss";
declare module "*.sass";
