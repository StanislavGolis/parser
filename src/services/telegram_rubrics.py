# src/services/telegram_rubrics.py
"""Рубрики автопостинга канала: «Свежее», «Раздел дня», «Топ недели».

Канал — витрина закрытого архива, и однообразная лента «дайджест за сутки» быстро
надоедает. Поэтому автопост собирается по **рубрикам**: у каждой свой шаблон текста,
свой набор кадров и свой минимальный интервал. Рубрики включаются и настраиваются в
админке (раздел «Канал» → вкладка «Рубрики»), планировщик сам решает, что
опубликовать (или отправить в карантин) сейчас.

Что делает каждая рубрика:

* `fresh` — **Свежее**: мозаика 2×2 из свежих файлов (по умолчанию с размытием 15),
  строка «свежее за сутки: +N файлов в M разделах», список разделов с приростом и по
  одному фото из каждого раздела в хорошем качестве;
* `board_day` — **Раздел дня**: несколько фото из одного треда в хорошем качестве,
  заголовок «РАЗДЕЛ // /slug — N файлов» и описание раздела из админки;
* `top_week` — **Топ недели**: мозаика 2×2 и разделы, которые смотрели и сохраняли
  за неделю (просмотры, скачивания, метки «отличный контент»).

Данные считаются по видимым файлам видимых разделов: премиум-контент в канал не
попадает, а работа с рубрикой идёт через белый список разделов автопостинга.
"""
from __future__ import annotations

import asyncio
import base64
import html
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import VISIBLE_FILTER, visible_thread_clause
from src.core.config import settings
from src.core.models import (
    Board,
    DownloadStat,
    Media,
    MediaMark,
    TelegramAutopost,
    TelegramPost,
    TelegramRubric,
    ViewStat,
)
from src.services import telegram_publisher
from src.services.analytics import record_audit

# Коды рубрик: те же строки лежат в `telegram_rubrics.code` и `telegram_posts.rubric`
CODES = ("fresh", "board_day", "top_week")
# Сколько кадров максимум уходит в один альбом (лимит Telegram — 10 в альбоме)
ALBUM_MAX = 10
MOSAIC_TILES = 4
QUALITIES = ("web", "thumb")

# Единый шаблон настроек рубрики: мозаика (обложка) и приложения (отдельные кадры).
# Ключи одинаковые у всех рубрик — в админке это две группы полей, а сама рубрика
# решает только, откуда брать файлы (свежие / тред раздела / популярные за неделю).
COMMON_DEFAULTS: Dict[str, Any] = {
    "tiles": 4,             # плиток мозаики: 0 — без мозаики, 4 — сетка 2×2
    "blur": 15,             # размытие мозаики (0…24)
    "photos": 4,            # сколько кадров приложить отдельными фото
    "photos_per_board": 1,  # по сколько кадров брать из каждого раздела
    "photos_blur": 0,       # размытие приложений: 0 — фото как есть
    "quality": "web",       # качество приложений: web | thumb
}

# Рубрики: общий шаблон плюс то, что специфично для каждой
DEFAULT_OPTIONS: Dict[str, Dict[str, Any]] = {
    "fresh": {**COMMON_DEFAULTS, "hours": 24, "boards_count": 4},
    "board_day": {**COMMON_DEFAULTS, "tiles": 0, "photos": 5, "board": ""},
    "top_week": {
        **COMMON_DEFAULTS,
        "tiles": 4,
        "photos": 0,
        "days": 7,
        "boards_count": 3,
        # activity — просмотры+скачивания+метки, growth — прирост, size — размер раздела
        "sort": "activity",
    },
}


def _int(options: Dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    """Целое из настроек рубрики с зажимом в границы — админ не сломает пост."""
    try:
        value = int(options.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _quality(options: Dict[str, Any]) -> str:
    """Какой дериватив идёт в альбом: `web` (хорошее качество) или `thumb`."""
    value = str(options.get("quality") or "web")
    return value if value in QUALITIES else "web"


def options_for(rubric: TelegramRubric) -> Dict[str, Any]:
    """Настройки рубрики: значения общего шаблона, перекрытые сохранёнными."""
    base = dict(DEFAULT_OPTIONS.get(rubric.code, {}))
    stored = dict(rubric.options or {})
    # Совместимость: раньше число приложений у «Свежего» называлось board_photos
    if "photos" not in stored and "board_photos" in stored:
        stored["photos"] = stored["board_photos"]
    stored.pop("board_photos", None)
    base.update(stored)
    return base


def bot_tag() -> str:
    """`@dredger_vip_bot` — как обращаемся к боту в текстах постов."""
    name = (settings.TELEGRAM_BOT_USERNAME or "").strip().lstrip("@")
    return f"@{name}" if name else "бота"


def bot_link(payload: str) -> str:
    """Ссылка в бота с меткой рубрики (`?start=fresh`) — видно, откуда пришёл человек."""
    return telegram_publisher.bot_url(settings.TELEGRAM_BOT_USERNAME, payload)


def bot_tail(action: str, payload: str) -> str:
    """Финальная строка поста: «Смотреть → @bot» (у альбома кнопок не бывает)."""
    tag = bot_tag()
    url = bot_link(payload)
    if not url:
        return f"<i>{html.escape(action)}</i> → {html.escape(tag)}"
    return f'<i>{html.escape(action)}</i> → <a href="{url}">{html.escape(tag)}</a>'


def trim_caption(text: str, limit: int = 1024) -> str:
    """Обрезает подпись под лимит Telegram (1024 у фото и альбома)."""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


async def list_rubrics(session: AsyncSession) -> List[TelegramRubric]:
    """Все рубрики в порядке приоритета — для админки и планировщика."""
    rows = await session.execute(
        select(TelegramRubric).order_by(TelegramRubric.sort_order, TelegramRubric.code)
    )
    return list(rows.scalars().all())


async def get_rubric(session: AsyncSession, code: str) -> Optional[TelegramRubric]:
    """Рубрика по коду (`fresh` | `board_day` | `top_week`)."""
    return (
        await session.execute(select(TelegramRubric).where(TelegramRubric.code == code))
    ).scalar_one_or_none()


def next_run_at(rubric: TelegramRubric) -> Optional[datetime]:
    """Когда рубрику можно собрать снова (после последнего запуска и паузы)."""
    if rubric.last_run_at is None:
        return None
    return rubric.last_run_at + timedelta(hours=max(1, int(rubric.min_gap_hours or 24)))


def is_due(rubric: TelegramRubric, now: Optional[datetime] = None) -> bool:
    """Пора ли собирать рубрику: включена и пауза между постами прошла."""
    if not rubric.enabled:
        return False
    moment = now or datetime.utcnow()
    due = next_run_at(rubric)
    return due is None or due <= moment


async def pick_rubric(
    session: AsyncSession, now: Optional[datetime] = None
) -> Optional[TelegramRubric]:
    """Выбирает рубрику для ближайшего автопоста.

    Берём самую «просроченную»: у «Свежего» пауза 12 часов, у «Раздела дня» — сутки,
    у «Топ недели» — неделя. Поэтому посты чередуются сами, а не повторяются подряд.
    Если ничего не готово — None, и планировщик просто пропускает проход.
    """
    moment = now or datetime.utcnow()
    ready = [row for row in await list_rubrics(session) if is_due(row, moment)]
    if not ready:
        return None

    def sort_key(row: TelegramRubric) -> tuple:
        due = next_run_at(row) or datetime.min
        return (due, int(row.sort_order or 0), row.code)

    return sorted(ready, key=sort_key)[0]


# ── Данные для рубрик ────────────────────────────────────────────────


@dataclass
class BoardStat:
    """Раздел в статистике рубрики: объём, прирост и вовлечённость за период."""

    slug: str
    title: str = ""
    total: int = 0
    fresh: int = 0
    views: int = 0
    downloads: int = 0
    marks: int = 0

    @property
    def activity(self) -> int:
        """«Смотрели и сохраняли»: просмотры плюс скачивания и метки с весом."""
        return self.views + self.downloads * 5 + self.marks * 10


def _clean_boards(boards: Optional[Sequence[str]]) -> List[str]:
    """Слаги из настроек автопостинга: без слэшей, повторов и пустых значений."""
    picked: List[str] = []
    for item in boards or []:
        slug = str(item).strip().lstrip("/")
        if slug and slug not in picked:
            picked.append(slug)
    return picked


def _has_asset(item: Media, quality: str = "web") -> bool:
    """Есть ли у файла дериватив, пригодный для канала (`web`, иначе превью)."""
    variants = item.variants or {}
    return bool(variants.get(quality) or variants.get("thumb") or variants.get("thumb_blur"))


async def board_stats(
    session: AsyncSession,
    *,
    days: int = 7,
    boards: Optional[Sequence[str]] = None,
) -> List[BoardStat]:
    """Статистика по разделам за период: объём, прирост, просмотры, скачивания, метки.

    Считаем только то, что может попасть в канал: видимые файлы видимых разделов и
    тредов, без премиум-контента.
    """
    since = datetime.utcnow() - timedelta(days=max(1, days))
    slugs = _clean_boards(boards)
    board_filter = [Board.slug.in_(slugs)] if slugs else []

    stats: Dict[str, BoardStat] = {}
    volume = await session.execute(
        select(
            Board.slug,
            Board.title,
            func.count(Media.id),
            func.count(Media.id).filter(Media.created_at >= since),
        )
        .join(Media, Media.board_id == Board.id)
        .where(
            Board.is_visible.is_(True),
            *VISIBLE_FILTER,
            visible_thread_clause(),
            Media.is_premium.is_(False),
            *board_filter,
        )
        .group_by(Board.slug, Board.title)
    )
    for slug, title, total, fresh in volume.all():
        stats[slug] = BoardStat(
            slug=slug, title=title or "", total=int(total or 0), fresh=int(fresh or 0)
        )

    async def tally(model, column, attr: str) -> None:
        """Складывает счётчик (просмотры/скачивания/метки) в статистику раздела."""
        rows = await session.execute(
            select(Board.slug, func.count(model.id))
            .join(Media, Media.board_id == Board.id)
            .join(model, model.media_id == Media.id)
            .where(
                Board.is_visible.is_(True),
                *VISIBLE_FILTER,
                visible_thread_clause(),
                Media.is_premium.is_(False),
                column >= since,
                *board_filter,
            )
            .group_by(Board.slug)
        )
        for slug, count in rows.all():
            item = stats.get(slug)
            if item is not None:
                setattr(item, attr, int(count or 0))

    await tally(ViewStat, ViewStat.viewed_at, "views")
    await tally(DownloadStat, DownloadStat.downloaded_at, "downloads")
    await tally(MediaMark, MediaMark.created_at, "marks")
    return list(stats.values())


def sort_stats(rows: List[BoardStat], mode: str = "activity") -> List[BoardStat]:
    """Порядок разделов в «Топе недели»: вовлечённость, прирост или объём."""
    if mode == "growth":
        return sorted(rows, key=lambda item: (-item.fresh, -item.total, item.slug))
    if mode == "size":
        return sorted(rows, key=lambda item: (-item.total, -item.fresh, item.slug))
    return sorted(rows, key=lambda item: (-item.activity, -item.fresh, item.slug))


async def board_media(
    session: AsyncSession,
    slugs: Sequence[str],
    *,
    per_board: int = 1,
    since: Optional[datetime] = None,
    images_only: bool = False,
    quality: str = "web",
    skip: Optional[Sequence[int]] = None,
) -> List[Media]:
    """Свежие файлы по одному (или больше) на раздел — для мозаики и приложений.

    Файл обязан иметь дериватив: кадр без превью в пост не поставить. Если в разделе
    таких не нашлось, раздел просто выпадает — пост от этого не ломается.
    """
    taken = {int(item) for item in (skip or [])}
    picked: List[Media] = []
    wanted = max(1, per_board)

    for slug in _clean_boards(slugs):
        rows = await session.execute(
            select(Media)
            .join(Board, Board.id == Media.board_id)
            .where(
                Board.slug == slug,
                Board.is_visible.is_(True),
                *VISIBLE_FILTER,
                visible_thread_clause(),
                Media.is_premium.is_(False),
                *([Media.created_at >= since] if since else []),
                *([Media.media_type == "image"] if images_only else []),
            )
            .order_by(Media.created_at.desc(), Media.id.desc())
            .limit(max(4, wanted * 4))
        )
        found = 0
        for item in rows.scalars().all():
            if item.id in taken or not _has_asset(item, quality):
                continue
            picked.append(item)
            taken.add(item.id)
            found += 1
            if found >= wanted:
                break
    return picked


async def latest_media(
    session: AsyncSession, *, limit: int = MOSAIC_TILES, quality: str = "thumb"
) -> List[Media]:
    """Самые свежие видимые файлы архива — запасной вариант для мозаики."""
    rows = await session.execute(
        select(Media)
        .join(Board, Board.id == Media.board_id)
        .where(
            Board.is_visible.is_(True),
            *VISIBLE_FILTER,
            visible_thread_clause(),
            Media.is_premium.is_(False),
        )
        .order_by(Media.created_at.desc(), Media.id.desc())
        .limit(limit * 4)
    )
    picked: List[Media] = []
    for item in rows.scalars().all():
        if _has_asset(item, quality):
            picked.append(item)
        if len(picked) >= limit:
            break
    return picked


async def top_media(
    session: AsyncSession,
    *,
    limit: int = MOSAIC_TILES,
    days: int = 7,
    boards: Optional[Sequence[str]] = None,
) -> List[Media]:
    """Что смотрели чаще всего за период — кадры для мозаики «Топ недели»."""
    since = datetime.utcnow() - timedelta(days=max(1, days))
    slugs = _clean_boards(boards)
    rows = await session.execute(
        select(Media, func.count(ViewStat.id).label("hits"))
        .join(Board, Board.id == Media.board_id)
        .join(ViewStat, ViewStat.media_id == Media.id)
        .where(
            Board.is_visible.is_(True),
            *VISIBLE_FILTER,
            visible_thread_clause(),
            Media.is_premium.is_(False),
            ViewStat.viewed_at >= since,
            *([Board.slug.in_(slugs)] if slugs else []),
        )
        .group_by(Media.id)
        .order_by(func.count(ViewStat.id).desc(), Media.created_at.desc())
        .limit(limit * 4)
    )
    picked: List[Media] = []
    for item, _hits in rows.all():
        if _has_asset(item, "thumb"):
            picked.append(item)
        if len(picked) >= limit:
            break
    return picked or await latest_media(session, limit=limit)


async def _board_row(session: AsyncSession, slug: str) -> Optional[Board]:
    """Раздел по слагу, если он видим (для заголовка и описания «Раздела дня»)."""
    return (
        await session.execute(
            select(Board).where(Board.slug == slug, Board.is_visible.is_(True))
        )
    ).scalar_one_or_none()


async def pick_board_of_day(
    session: AsyncSession, *, boards: Optional[Sequence[str]] = None, preferred: str = ""
) -> Optional[Board]:
    """Раздел дня: либо заданный в настройках, либо ротация.

    Ротация честная: сначала идут разделы, которые давно не попадали в рубрику
    `board_day` (смотрим `telegram_posts.rubric_meta->>'board'`), а среди равных —
    те, где больше свежих файлов. Так «Раздел дня» не застревает на одном разделе.
    """
    wanted = _clean_boards([preferred])
    if wanted:
        return await _board_row(session, wanted[0])

    candidates = [
        item for item in await board_stats(session, days=30, boards=boards) if item.total > 0
    ]
    if not candidates:
        return None

    last_used: Dict[str, datetime] = {}
    history = await session.execute(
        select(TelegramPost.rubric_meta, TelegramPost.created_at)
        .where(
            TelegramPost.rubric == "board_day",
            TelegramPost.status.in_(("draft", "scheduled", "published")),
            TelegramPost.rubric_meta.isnot(None),
        )
        .order_by(TelegramPost.created_at.desc())
        .limit(200)
    )
    # Постов рубрики немного, поэтому «когда раздел показывали в последний раз»
    # считаем в Python: группировка по JSONB-полю ломается на bind-параметрах.
    for meta, created_at in history.all():
        slug = str((meta or {}).get("board") or "").strip()
        if slug and slug not in last_used:
            last_used[slug] = created_at

    chosen = sorted(
        candidates,
        key=lambda item: (last_used.get(item.slug) or datetime.min, -item.fresh, item.slug),
    )[0]
    return await _board_row(session, chosen.slug)


async def thread_media(
    session: AsyncSession,
    board: Board,
    *,
    limit: int = 5,
    quality: str = "web",
    images_only: bool = True,
) -> List[Media]:
    """Кадры из одного треда раздела — галерея «Раздела дня».

    Тред выбираем по количеству свежих файлов (за 30 дней), если таких нет — самый
    наполненный тред раздела. Внутри треда показываем начало по `source_order`: так
    порядок совпадает с просмотром треда на сайте.
    """
    filters = [
        Board.slug == board.slug,
        Board.is_visible.is_(True),
        *VISIBLE_FILTER,
        visible_thread_clause(),
        Media.is_premium.is_(False),
        *([Media.media_type == "image"] if images_only else []),
    ]
    since = datetime.utcnow() - timedelta(days=30)

    async def first_thread(with_since: bool):
        query = (
            select(Media.thread_id, func.count(Media.id))
            .join(Board, Board.id == Media.board_id)
            .where(*filters, *([Media.created_at >= since] if with_since else []))
            .group_by(Media.thread_id)
            .order_by(func.count(Media.id).desc())
            .limit(1)
        )
        return (await session.execute(query)).first()

    thread = await first_thread(True) or await first_thread(False)
    if thread is None:
        return []

    rows = await session.execute(
        select(Media)
        .join(Board, Board.id == Media.board_id)
        .where(*filters, Media.thread_id == int(thread[0]))
        .order_by(Media.source_order.asc().nullslast(), Media.id.asc())
        .limit(max(4, limit * 4))
    )
    picked: List[Media] = []
    for item in rows.scalars().all():
        if _has_asset(item, quality):
            picked.append(item)
        if len(picked) >= limit:
            break
    return picked


# ── Сборка постов ────────────────────────────────────────────────────


@dataclass
class RubricBuild:
    """Готовый пост рубрики: текст, кадры и разбивка для альбома."""

    code: str
    caption: str
    image_mode: str = "mosaic"       # mosaic | single | album | none
    blur: int = 0                    # размытие мозаики
    photos_blur: int = 0             # размытие приложений
    quality: str = "web"
    tiles: List[int] = field(default_factory=list)     # кадры мозаики (по порядку)
    photos: List[int] = field(default_factory=list)    # приложения в хорошем качестве
    boards: List[str] = field(default_factory=list)    # разделы, о которых пост
    board: str = ""                                    # «Раздел дня»: какой раздел

    @property
    def media_ids(self) -> List[int]:
        """Все файлы поста: мозаика + приложения (без повторов)."""
        picked = list(self.tiles)
        picked.extend(item for item in self.photos if item not in picked)
        return picked

    @property
    def meta(self) -> Dict[str, Any]:
        """Разбивка для `telegram_posts.rubric_meta` — по ней пост собирается заново."""
        data: Dict[str, Any] = {
            "blur": self.blur,
            "photos_blur": self.photos_blur,
            "quality": self.quality,
        }
        if self.tiles:
            data["tiles"] = self.tiles
        if self.photos:
            data["photos"] = self.photos
        if self.boards:
            data["boards"] = self.boards
        if self.board:
            data["board"] = self.board
        return data


def image_mode(tiles: int, photos: int) -> str:
    """Как отправлять собранное: альбом, одно фото-мозаика, одиночный кадр или текст."""
    if photos >= 1 and (tiles or photos > 1):
        return "album"
    if photos == 1:
        return "single"
    if tiles:
        return "mosaic"
    return "none"



def boards_in_phrase(value: int) -> str:
    """«в 6 разделах» / «в 1 разделе» — предложный падеж для строки про свежее."""
    number = abs(int(value))
    word = "разделе" if number % 10 == 1 and number % 100 != 11 else "разделах"
    return f"в {telegram_publisher.human_count(number)} {word}"


def fresh_caption(
    *, fresh_total: int, boards_total: int, rows: List[BoardStat], hours: int = 24
) -> str:
    """«Свежее»: прирост за период, перечень разделов и призыв в бота."""
    span = "за сутки" if hours == 24 else f"за {hours} ч"
    lines = ["<b>Свежее.</b>", ""]
    lines.append(
        f"Свежее {span}: <b>+{telegram_publisher.human_count(fresh_total)}</b> "
        f"{telegram_publisher.plural(fresh_total, 'файл', 'файла', 'файлов')} "
        f"{boards_in_phrase(boards_total)}."
    )
    lines.append("")
    for row in rows:
        lines.append(f"/{row.slug} — {telegram_publisher.human_count(row.fresh)}")
    lines.append("")
    lines.append(bot_tail("Всё — в боте", "fresh"))
    return trim_caption("\n".join(lines))


def board_day_caption(*, slug: str, total: int, description: str, title: str = "") -> str:
    """«Раздел дня»: заголовок с числом файлов и описание раздела из админки."""
    lines = [f"<b>РАЗДЕЛ</b> // /{slug} — <b>{telegram_publisher.files_phrase(total)}</b>", ""]
    body = (description or "").strip() or f"Раздел архива «{title or slug}»: подборка материалов."
    lines.append(html.escape(body))
    lines.append("")
    lines.append(bot_tail("Смотреть", "board_day"))
    return trim_caption("\n".join(lines))


def top_week_caption(*, rows: List[BoardStat], days: int = 7) -> str:
    """«Топ недели»: что смотрели и сохраняли, объём разделов и прирост."""
    span = "на этой неделе" if days >= 7 else f"за последние {days} дн."
    lines = ["<b>ТОП // НЕДЕЛЯ</b>", "", f"Что смотрели и сохраняли {span}:"]
    for row in rows:
        # Если раздел целиком появился за период, «+N» рядом с объёмом только путает
        growth = (
            f", +{telegram_publisher.human_count(row.fresh)}"
            if 0 < row.fresh < row.total
            else ""
        )
        lines.append(
            f"— /{row.slug}: <b>{telegram_publisher.files_phrase(row.total)}</b>{growth}"
        )
    lines.append("")
    lines.append(bot_tail("Полный топ — в боте", "top_week"))
    return trim_caption("\n".join(lines))


async def _build_fresh(
    session: AsyncSession, options: Dict[str, Any], boards: Optional[Sequence[str]]
) -> Optional[RubricBuild]:
    """«Свежее»: мозаика из свежих файлов, разделы с приростом и фото из разделов."""
    hours = _int(options, "hours", 24, 1, 336)
    boards_count = _int(options, "boards_count", 4, 1, 6)
    tiles_wanted = _int(options, "tiles", MOSAIC_TILES, 0, MOSAIC_TILES)
    photos_wanted = _int(options, "photos", 4, 0, ALBUM_MAX)
    per_board = _int(options, "photos_per_board", 1, 1, 3)
    blur = _int(options, "blur", 15, 0, 24)
    photos_blur = _int(options, "photos_blur", 0, 0, 24)
    quality = _quality(options)
    days = max(1, (hours + 23) // 24)
    since = datetime.utcnow() - timedelta(hours=hours)

    stats = [item for item in await board_stats(session, days=days, boards=boards) if item.fresh > 0]
    if not stats:
        return None
    stats = sorted(stats, key=lambda item: (-item.fresh, item.slug))
    shown = stats[:boards_count]
    slugs = [item.slug for item in shown]

    # Мозаика 2×2: по одному свежему файлу из ведущих разделов, остальное — добираем
    tiles: List[Media] = []
    if tiles_wanted:
        tiles = await board_media(session, slugs, per_board=1, since=since, quality="thumb")
        if len(tiles) < tiles_wanted:
            extra = await latest_media(session, limit=tiles_wanted - len(tiles), quality="thumb")
            taken = {item.id for item in tiles}
            tiles.extend(item for item in extra if item.id not in taken)
        tiles = tiles[:tiles_wanted]

    # Приложения: свежие фото разделов (по `photos_per_board` с каждого) в хорошем качестве
    photos: List[Media] = []
    if photos_wanted:
        photos = await board_media(
            session,
            slugs,
            per_board=per_board,
            since=since,
            images_only=True,
            quality=quality,
            skip=[item.id for item in tiles],
        )
        photos = photos[: min(photos_wanted, ALBUM_MAX - (1 if tiles else 0))]

    if not tiles and not photos:
        return None

    return RubricBuild(
        code="fresh",
        caption=fresh_caption(
            fresh_total=sum(item.fresh for item in stats),
            boards_total=len(stats),
            rows=shown,
            hours=hours,
        ),
        image_mode=image_mode(len(tiles), len(photos)),
        blur=blur,
        photos_blur=photos_blur,
        quality=quality,
        tiles=[item.id for item in tiles],
        photos=[item.id for item in photos],
        boards=slugs,
    )


async def _build_board_day(
    session: AsyncSession, options: Dict[str, Any], boards: Optional[Sequence[str]]
) -> Optional[RubricBuild]:
    """«Раздел дня»: галерея из одного треда раздела и описание раздела."""
    tiles_wanted = _int(options, "tiles", 0, 0, MOSAIC_TILES)
    photos_wanted = _int(options, "photos", 5, 0, ALBUM_MAX)
    blur = _int(options, "blur", 15, 0, 24)
    photos_blur = _int(options, "photos_blur", 0, 0, 24)
    quality = _quality(options)
    if not tiles_wanted and not photos_wanted:
        return None

    board = await pick_board_of_day(
        session, boards=boards, preferred=str(options.get("board") or "")
    )
    if board is None:
        return None

    stats = {item.slug: item for item in await board_stats(session, days=30, boards=[board.slug])}
    pool = await thread_media(
        session, board, limit=min(ALBUM_MAX, tiles_wanted + photos_wanted), quality=quality
    )
    if not pool:
        return None
    tiles = pool[:tiles_wanted]
    photos = pool[tiles_wanted : tiles_wanted + photos_wanted]

    return RubricBuild(
        code="board_day",
        caption=board_day_caption(
            slug=board.slug,
            total=stats[board.slug].total if board.slug in stats else len(pool),
            description=board.description or "",
            title=board.title or "",
        ),
        image_mode=image_mode(len(tiles), len(photos)),
        blur=blur,
        photos_blur=photos_blur,
        quality=quality,
        tiles=[item.id for item in tiles],
        photos=[item.id for item in photos],
        boards=[board.slug],
        board=board.slug,
    )


async def _build_top_week(
    session: AsyncSession, options: Dict[str, Any], boards: Optional[Sequence[str]]
) -> Optional[RubricBuild]:
    """«Топ недели»: мозаика из популярного и разделы, которые смотрели за неделю."""
    days = _int(options, "days", 7, 2, 30)
    boards_count = _int(options, "boards_count", 3, 1, 6)
    tiles_wanted = _int(options, "tiles", MOSAIC_TILES, 0, MOSAIC_TILES)
    photos_wanted = _int(options, "photos", 0, 0, ALBUM_MAX)
    blur = _int(options, "blur", 15, 0, 24)
    photos_blur = _int(options, "photos_blur", 0, 0, 24)
    quality = _quality(options)
    mode = str(options.get("sort") or "activity")
    if not tiles_wanted and not photos_wanted:
        return None

    stats = await board_stats(session, days=days, boards=boards)
    rows = sort_stats([item for item in stats if item.total > 0], mode)[:boards_count]
    if not rows:
        return None

    pool = await top_media(
        session,
        limit=min(ALBUM_MAX, tiles_wanted + photos_wanted),
        days=days,
        boards=[item.slug for item in rows],
    )
    tiles = pool[:tiles_wanted]
    photos = pool[tiles_wanted : tiles_wanted + photos_wanted]
    if not tiles and not photos:
        return None

    return RubricBuild(
        code="top_week",
        caption=top_week_caption(rows=rows, days=days),
        image_mode=image_mode(len(tiles), len(photos)),
        blur=blur,
        photos_blur=photos_blur,
        quality=quality,
        tiles=[item.id for item in tiles],
        photos=[item.id for item in photos],
        boards=[item.slug for item in rows],
    )



async def build(
    session: AsyncSession,
    rubric: TelegramRubric,
    *,
    boards: Optional[Sequence[str]] = None,
) -> Optional[RubricBuild]:
    """Собирает пост рубрики; None — если показывать нечего (пустой архив/раздел)."""
    options = options_for(rubric)
    code = rubric.code if rubric.code in CODES else "fresh"
    if code == "board_day":
        return await _build_board_day(session, options, boards)
    if code == "top_week":
        return await _build_top_week(session, options, boards)
    return await _build_fresh(session, options, boards)


async def make_post(
    session: AsyncSession,
    s3,
    rubric: TelegramRubric,
    row: TelegramAutopost,
    *,
    actor: str = "autopost",
    publish: bool = False,
) -> Optional[TelegramPost]:
    """Собирает пост рубрики и отправляет его в карантин (или сразу в канал).

    По умолчанию работает карантин: админ получает черновик в ЛС бота. При
    `require_approval=False` или `publish=True` пост уходит в канал сразу.
    `rubric.last_run_at` двигаем в любом случае — иначе планировщик будет слать
    черновики каждую минуту.
    """
    from src.services import telegram_service  # локально: сервис не зависит от рубрик

    result = await build(session, rubric, boards=row.boards)
    if result is None:
        return None

    label, url = telegram_service.button_for(None, None)
    post = telegram_service.build_post(
        kind="rubric",
        caption=result.caption,
        media_ids=result.media_ids,
        image_mode=result.image_mode,
        button_text=label,
        button_url=url,
        actor=actor,
        status="draft",
    )
    post.rubric = rubric.code
    post.rubric_meta = result.meta
    session.add(post)
    await session.flush()

    if row.require_approval and not publish:
        delivered = await telegram_service.send_draft_to_admins(session, s3, post)
        if delivered == 0:
            post.error = "Черновик создан, но админам не доставлен: никто не запускал бота"
    else:
        await telegram_service._deliver(
            session, s3, post, None, label=label, url=url, blur=result.blur
        )

    rubric.last_run_at = datetime.utcnow()
    await record_audit(
        session,
        action="telegram.rubric",
        target=str(post.id),
        details=(
            f"{rubric.code}: {post.status} (кадров: {len(result.media_ids)}"
            + (f", раздел: {result.board}" if result.board else "")
            + ")"
        ),
    )
    await session.commit()
    await session.refresh(post)
    return post


async def preview(
    session: AsyncSession,
    s3,
    rubric: TelegramRubric,
    *,
    boards: Optional[Sequence[str]] = None,
    max_images: int = ALBUM_MAX,
) -> Dict[str, Any]:
    """Предпросмотр рубрики: текст и уменьшенные кадры — без записи и публикации."""
    from src.services import telegram_service

    result = await build(session, rubric, boards=boards)
    if result is None:
        return {
            "caption": "",
            "image_mode": "none",
            "images": [],
            "media_ids": [],
            "boards": [],
            "board": "",
            "tiles": [],
            "photos": [],
            "blur": 0,
            "photos_blur": 0,
            "note": "Пока нечего показать: в архиве нет подходящих файлов",
        }

    draft = telegram_service.build_post(
        kind="rubric",
        caption=result.caption,
        media_ids=result.media_ids,
        image_mode=result.image_mode,
        button_text="",
        button_url="",
        actor="preview",
    )
    draft.rubric_meta = result.meta
    images = await telegram_service.post_images(session, s3, draft, blur=result.blur)

    # Для предпросмотра в админке кадры ужимаем: полные версии — только в канал
    thumbs: List[str] = []
    for payload in images[: max(1, max_images)]:
        small = await asyncio.to_thread(
            telegram_publisher.to_jpeg, payload, max_side=800, quality=70
        )
        if small:
            thumbs.append("data:image/jpeg;base64," + base64.b64encode(small).decode("ascii"))

    cover = 1 if result.tiles else 0
    return {
        "caption": result.caption,
        "image_mode": result.image_mode,
        "images": thumbs,
        "media_ids": result.media_ids,
        "boards": result.boards,
        "board": result.board,
        "tiles": result.tiles,
        "photos": result.photos,
        "blur": result.blur,
        "photos_blur": result.photos_blur,
        "note": (
            f"кадров в посте: {len(images)} "
            f"(мозаика: {cover}, приложений: {len(result.photos)})"
        ),
    }




