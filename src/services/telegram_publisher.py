# src/services/telegram_publisher.py
"""Сборка тизера для Telegram-канала: картинка-мозаика и текст подписи.

Модель Dredger 2.0: канал — витрина, весь архив за логином. Отсюда два правила,
которые зашиты в этот модуль:

* пост ведёт **в бота** (кнопка «Открыть в боте»), а не на закрытый сайт;
* картинка собирается из наших же превью и **размывается** — канал не должен
  ловить блокировку за adult-контент (Telegram банит за это каналы и ботов).

Подписи шаблонные: имена файлов в архиве часто технические, поэтому в тексте
перечисляем разделы и цифры, а не названия файлов.
"""
from __future__ import annotations

import html
import io
from typing import Iterable, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# 16:9 — стандарт для превью в Telegram, влезает в «квадратную» обрезку канала
TEASER_WIDTH = 1280
TEASER_HEIGHT = 720
TILES = 4
# Размытие по умолчанию: контент в канале должен быть «мягким»
DEFAULT_BLUR = 7
DARKEN = 0.35  # затемнение поверх мозаики, чтобы подпись читалась

KIND_LABELS = {
    "teaser": "Свежее в архиве",
    "digest": "Топ архива",
    "announce": "Новости",
}


def _font(size: int) -> ImageFont.ImageFont:
    """Шрифт для подписи: с запасными вариантами, чтобы не падать без TTF."""
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:  # noqa: BLE001 — шрифт может отсутствовать в образе
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow ≥ 10.1
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def _fit_tile(data: bytes, width: int, height: int) -> Optional[Image.Image]:
    """Плитка мозаики: кадр обрезается по центру под нужный размер."""
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:  # noqa: BLE001 — битый дериватив не должен ронять пост
        return None

    # «object-cover»: масштабируем по большей стороне и обрезаем по центру
    scale = max(width / img.width, height / img.height)
    resized = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def build_teaser_image(tiles: Iterable[bytes], *, blur: int = DEFAULT_BLUR) -> Optional[bytes]:
    """Собирает картинку тизера 1280×720: мозаика 2×2 + размытие + подпись.

    `tiles` — байты превью (JPEG/WebP): у картинок это `thumb`, у видео — постер.
    Возвращает JPEG или None, если ни одна плитка не подошла.
    """
    prepared = [tile for tile in (_fit_tile(data, TEASER_WIDTH // 2, TEASER_HEIGHT // 2) for data in tiles) if tile]
    if not prepared:
        return None

    canvas = Image.new("RGB", (TEASER_WIDTH, TEASER_HEIGHT), (10, 12, 15))
    cell_w, cell_h = TEASER_WIDTH // 2, TEASER_HEIGHT // 2
    for index, tile in enumerate(prepared[:TILES]):
        column, row = index % 2, index // 2
        canvas.paste(tile, (column * cell_w, row * cell_h))

    # Размытие: контент в канале показываем «мягко», без явной обнажёнки
    if blur > 0:
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius=blur))

    if DARKEN > 0:
        veil = Image.new("RGB", canvas.size, (0, 0, 0))
        canvas = Image.blend(canvas, veil, DARKEN)

    draw = ImageDraw.Draw(canvas)
    title_font = _font(84)
    sub_font = _font(30)
    draw.text((56, TEASER_HEIGHT - 210), "DREDGER", font=title_font, fill=(255, 255, 255))
    draw.text((58, TEASER_HEIGHT - 104), "архив // отбор // доступ", font=sub_font, fill=(190, 200, 210))

    buffer = io.BytesIO()
    canvas.save(buffer, "JPEG", quality=86, optimize=True)
    return buffer.getvalue()


def build_caption(
    kind: str,
    *,
    boards: list[str],
    media_total: int,
    media_today: int = 0,
    text: Optional[str] = None,
    bot_username: str = "",
    site_note: str = "",
    period: Optional[str] = None,
) -> str:
    """Текст подписи к посту: шаблон по типу поста + подпись канала.

    Используется HTML-разметка Telegram (`<b>`, `<i>`) — весь внешний текст
    экранируется, чтобы техническое имя не сломало отправку.
    """
    kind = kind if kind in KIND_LABELS else "teaser"
    lines: list[str] = []

    if text:
        lines.append(html.escape(text.strip()))
        lines.append("")

    label = KIND_LABELS[kind]
    if kind == "digest":
        span = "за неделю" if period == "week" else "за сутки"
        label = f"{label} · {span}"
    lines.append(f"<b>{label}</b>")

    if boards:
        listed = ", ".join(f"/{html.escape(name.lstrip('/'))}" for name in boards[:4])
        lines.append(f"Разделы: {listed}")
    if media_total:
        fresh = f" · +{media_today} за сутки" if media_today else ""
        lines.append(f"Файлов в подборке: <b>{media_total}</b>{fresh}")

    note = site_note or ("Больше — за подпиской, вход через бота." if bot_username else "")
    if note:
        lines.append("")
        lines.append(f"<i>{html.escape(note)}</i>")

    return "\n".join(lines).strip()


def bot_url(bot_username: str, payload: str = "channel") -> str:
    """Ссылка на бота: для кнопки под постом (сайт закрытый — ссылку не даём)."""
    name = (bot_username or "").strip().lstrip("@")
    if not name:
        return ""
    return f"https://t.me/{name}?start={payload}" if payload else f"https://t.me/{name}"
