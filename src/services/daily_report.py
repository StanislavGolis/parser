# src/services/daily_report.py
"""Ежедневный отчёт на почту: за прошедшие отчётные сутки (по МСК).

Период — тот же, что и везде в проекте (`services/reporting`): с 00:00 до 00:00
МСК. Отчёт собирается сразу после закрытия суток (в 00:05 МСК) и отправляется
адресатам из `DAILY_REPORT_EMAILS` (по умолчанию — админы из `ADMIN_EMAILS`).

Варианты состава (`DAILY_REPORT_MODE`):

* `short`    — одна строка: «добавлено файлов N в M тредов в K разделах,
               уникальных посетителей P»;
* `standard` — строка + блок контента (картинки/видео, объём, топ разделов),
               люди (посетители/просмотры/новые аккаунты), активность (метки,
               прогоны) — вариант по умолчанию;
* `full`     — всё то же + ошибки прогонов и служебные детали (режим для отладки).

Текст письма можно посмотреть в админке, не отправляя его
(`GET /api/v1/admin/reports/daily`).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.services import mailer, reporting

MODE_SHORT = "short"
MODE_STANDARD = "standard"
MODE_FULL = "full"


def recipients() -> List[str]:
    """Адресаты отчёта: свои из настроек, иначе — админы."""
    raw = (settings.DAILY_REPORT_EMAILS or "").strip()
    if raw:
        return [e.strip() for e in raw.split(",") if e.strip()]
    return settings.admin_emails


def subject(stats: Dict[str, Any]) -> str:
    """Тема письма: сразу видно, был ли день пустым."""
    files = stats["files_added"]
    visitors = stats["visitors"]
    if not files and not visitors:
        return f"Dredger: за сутки тихо ({reporting.label(stats['start'])})"
    return (
        f"Dredger: +{files} файлов, {visitors} посетителей "
        f"({reporting.label(stats['start'])})"
    )


def headline(stats: Dict[str, Any]) -> str:
    """Главная строка отчёта — «добавлено файлов N в M тредов в K разделах»."""
    files = stats["files_added"]
    threads = stats["threads_touched"]
    boards = stats["boards_touched"]
    visitors = stats["visitors"]
    return (
        f"Добавлено файлов {files} в {threads} {_plural(threads, 'тред', 'треда', 'тредов')} "
        f"в {boards} {_plural(boards, 'разделе', 'разделах', 'разделах')}. "
        f"Уникальных посетителей: {visitors}."
    )


def _plural(count: int, one: str, few: str, many: str) -> str:
    """Русское склонение: 1 файл / 2 файла / 5 файлов."""
    if count % 10 == 1 and count % 100 != 11:
        return one
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return few
    return many


def build_text(stats: Dict[str, Any], top: List[Dict[str, Any]], failures: List[Dict[str, Any]]) -> str:
    """Текст письма. `stats` — из `reporting.daily_stats`."""
    start, end = stats["start"], stats["end"]
    mode = (settings.DAILY_REPORT_MODE or MODE_STANDARD).lower()
    lines = [
        f"Отчёт за {reporting.period_title(start, end)}",
        "",
        headline(stats),
    ]

    if mode in (MODE_STANDARD, MODE_FULL):
        lines += [
            "",
            "Контент:",
            f"  файлов: {stats['files_added']} "
            f"(картинок {stats['images_added']}, видео {stats['videos_added']})",
            f"  объём: {reporting.human_bytes(stats['bytes_added'])}",
        ]
        if top:
            lines.append("  разделы:")
            for item in top:
                lines.append(f"    /{item['slug']} — {item['files']}")

        lines += [
            "",
            "Посетители:",
            f"  уникальных: {stats['visitors']} (из них новых: {stats['visitors_new']})",
            f"  просмотров страниц: {stats['page_views']} "
            f"(в среднем {stats['page_views_per_visitor']} на посетителя)",
            f"  сессий: {stats['sessions']}",
            "",
            "Активность:",
            f"  новые аккаунты: {stats['new_users']}",
            f"  метки «отличный контент»: {stats['marks']}",
            f"  прогоны парсера: {stats['runs_ok']} успешных, {stats['runs_error']} с ошибками",
        ]

    if mode == MODE_FULL and failures:
        lines += ["", "Ошибки прогонов:"]
        for item in failures:
            lines.append(f"  {reporting.label(item['at'], with_time=True)}: {item['error']}")

    lines += [
        "",
        f"— Dredger, автоматический отчёт ({reporting.label(datetime.utcnow(), with_time=True)})",
    ]
    return "\n".join(lines)


async def build_report(
    session: AsyncSession, start: datetime, end: datetime
) -> Dict[str, Any]:
    """Готовит отчёт (текст + цифры) за указанный период."""
    stats = await reporting.daily_stats(session, start, end)
    top = await reporting.top_boards(session, start, end, limit=5)
    failures = await reporting.parse_failures(session, start, end)
    return {
        "period_start": start,
        "period_end": end,
        "period_label": reporting.period_title(start, end),
        "mode": (settings.DAILY_REPORT_MODE or MODE_STANDARD).lower(),
        "subject": subject(stats),
        "text": build_text(stats, top, failures),
        "stats": stats,
        "top_boards": top,
        "failures": failures,
        "recipients": recipients(),
        "mail_configured": mailer.is_configured(),
    }


async def send_report(text: str, mail_subject: str) -> List[str]:
    """Отправляет отчёт адресатам. Возвращает список тех, кому ушло."""
    sent: List[str] = []
    for address in recipients():
        if await mailer.send_mail(address, mail_subject, text):
            sent.append(address)
    return sent
