"""Источники контента: реестр, ключи Redis и журнал прогонов.

Каждый источник парсится своим адаптером и **независимым прогоном**:
- флаги запуска: `parser:{code}:enabled|up|alive|current|progress` (свой набор
  у каждого источника — пауза одного не трогает другой);
- настройки (базовый URL, конфиг адаптера, расписание, вежливость, бюджет) —
  строка в `sources`;
- итоги циклов — `parse_runs`: переживают перезапуск контейнера и показываются
  в админке во вкладке источника.

Совместимость: у источника `dvach` какое-то время читаются и старые (глобальные)
ключи `parser:enabled`, `parser:up`, `parser:alive`, `parser:current_board`,
`parser:progress` — прод обновляется без даунтайма и без «прыгающих» кнопок.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import ParseRun, Source
from src.core.redis_client import redis_client
from src.parsers import SourceAdapter, build_adapter

# Источник, с которого начинался проект (его ключи и были «глобальными»)
DEFAULT_SOURCE_CODE = "dvach"

# Пока источник-наследник не переведён на свой namespace, читаем и его старые ключи
LEGACY_KEYS: Dict[str, Dict[str, str]] = {
    DEFAULT_SOURCE_CODE: {
        "enabled": "parser:enabled",
        "up": "parser:up",
        "alive": "parser:alive",
        "current": "parser:current_board",
        "progress": "parser:progress",
    }
}

# TTL «живости» парсера: тот же, что был у одиночного демона
HEARTBEAT_TTL = 45
# TTL прогресса прогона (админка опрашивает его раз в секунду)
PROGRESS_TTL = 300


@dataclass(frozen=True)
class SourceKeys:
    """Пространство имён одного источника в Redis."""

    code: str
    enabled: str
    up: str
    alive: str
    current: str
    progress: str


def keys(code: str) -> SourceKeys:
    """Ключи источника: `parser:{code}:…` (каждый источник независим)."""
    return SourceKeys(
        code=code,
        enabled=f"parser:{code}:enabled",
        up=f"parser:{code}:up",
        alive=f"parser:{code}:alive",
        current=f"parser:{code}:current",
        progress=f"parser:{code}:progress",
    )


async def _get_with_legacy(code: str, field: str) -> Optional[str]:
    """Значение ключа: сначала новое имя, затем (для dvach) старое."""
    value = await redis_client.get(getattr(keys(code), field))
    if value is None:
        legacy = LEGACY_KEYS.get(code, {}).get(field)
        if legacy:
            value = await redis_client.get(legacy)
    return value


async def is_enabled(code: str) -> bool:
    """Включён ли прогон этого источника (кнопка «Запустить» в его вкладке)."""
    return (await _get_with_legacy(code, "enabled")) == "1"


async def set_enabled(code: str, enabled: bool) -> None:
    """Запустить/остановить прогон источника (свой флаг у каждого источника)."""
    k = keys(code)
    if enabled:
        await redis_client.set(k.enabled, "1")
        return
    await redis_client.set(k.enabled, "0")
    # На паузе снимаем «живость» сразу: админка не должна показывать «работает»
    await redis_client.delete(k.alive)
    await redis_client.delete(k.current)
    await redis_client.delete(k.progress)


async def heartbeat(code: str, *, running: bool, current: Optional[str] = None) -> None:
    """Обновляет ключи живости источника (вызывает цикл его прогона)."""
    k = keys(code)
    await redis_client.set(k.up, "1", ex=HEARTBEAT_TTL + 15)
    if not running:
        await redis_client.delete(k.alive)
        await redis_client.delete(k.current)
        await _mirror_legacy(code, up="1", alive=None, current=None)
        return
    await redis_client.set(k.alive, "1", ex=HEARTBEAT_TTL)
    if current:
        await redis_client.set(k.current, current, ex=HEARTBEAT_TTL)
    # Пока админка не перешла на реестр источников, источник по умолчанию (2ch)
    # дублирует живость в старые ключи — панель показывает прогресс как раньше.
    await _mirror_legacy(code, up="1", alive="1", current=current)


async def write_progress(code: str, payload: Dict[str, Any]) -> None:
    """Публикует прогресс прогона источника (TTL 5 минут).

    Прогресс у каждого источника свой (`parser:{code}:progress`); для источника по
    умолчанию он дублируется в старый ключ `parser:progress` — на него смотрит
    текущая админка.
    """
    raw = json.dumps(payload, ensure_ascii=False)
    try:
        await redis_client.set(keys(code).progress, raw, ex=PROGRESS_TTL)
        legacy = LEGACY_KEYS.get(code, {}).get("progress")
        if legacy:
            await redis_client.set(legacy, raw, ex=PROGRESS_TTL)
    except Exception:
        pass  # прогресс — не повод ронять прогон


async def touch_progress(code: str) -> None:
    """Освежает `updated_at` прогресса, пока прогон жив.

    Вызывается heartbeat-таском демона: скачивание большого видео может занимать
    минуты, за которые прогресс не переписывается, и админка показывала «простой
    N с — возможно завис» у работающего парсера. Если процесс умрёт, ключ истечёт
    по TTL и живость (`parser:{code}:alive`) пропадёт — это и есть честный признак
    «связи нет».
    """
    key = keys(code).progress
    try:
        raw = await redis_client.get(key)
        if not raw:
            return
        payload = json.loads(raw)
        payload["updated_at"] = datetime.utcnow().isoformat() + "Z"
        fresh = json.dumps(payload, ensure_ascii=False)
        await redis_client.set(key, fresh, ex=PROGRESS_TTL)
        legacy = LEGACY_KEYS.get(code, {}).get("progress")
        if legacy:
            await redis_client.set(legacy, fresh, ex=PROGRESS_TTL)
    except Exception:
        pass  # прогресс — не повод ронять прогон


async def clear_progress(code: str) -> None:
    """Снимает прогресс источника (прогон закончился/остановлен)."""
    try:
        await redis_client.delete(keys(code).progress)
        legacy = LEGACY_KEYS.get(code, {}).get("progress")
        if legacy:
            await redis_client.delete(legacy)
    except Exception:
        pass


async def _mirror_legacy(
    code: str,
    *,
    up: Optional[str] = None,
    alive: Optional[str] = None,
    current: Optional[str] = None,
) -> None:
    """Дублирует ключи живости в старые имена (только для источника `dvach`)."""
    legacy = LEGACY_KEYS.get(code)
    if not legacy:
        return
    try:
        if up is not None:
            await redis_client.set(legacy["up"], up, ex=HEARTBEAT_TTL + 15)
        for field, value in (("alive", alive), ("current", current)):
            key = legacy.get(field)
            if not key:
                continue
            if value:
                await redis_client.set(key, value, ex=HEARTBEAT_TTL)
            else:
                await redis_client.delete(key)
    except Exception:
        pass


async def read_status(code: str) -> Dict[str, Any]:
    """Состояние прогона источника: флаги + прогресс (для админки)."""
    enabled = await is_enabled(code)
    up = (await _get_with_legacy(code, "up")) == "1"
    alive = enabled and (await _get_with_legacy(code, "alive")) == "1"
    current = await _get_with_legacy(code, "current") if enabled else None
    raw_progress = await _get_with_legacy(code, "progress") if enabled else None
    progress: Optional[Dict[str, Any]] = None
    if raw_progress:
        try:
            progress = json.loads(raw_progress)
        except (TypeError, ValueError):
            progress = None
    return {
        "code": code,
        "enabled": enabled,
        "up": up,
        "alive": alive,
        "current": current,
        "progress": progress,
    }


# ── Реестр источников в БД ──────────────────────────────────────────


async def list_sources(session: AsyncSession) -> List[Source]:
    """Все источники в порядке отображения (для вкладок в админке)."""
    result = await session.execute(select(Source).order_by(Source.sort_order, Source.code))
    return list(result.scalars().all())


async def get_source(session: AsyncSession, code: str) -> Optional[Source]:
    result = await session.execute(select(Source).where(Source.code == code))
    return result.scalar_one_or_none()


def build_source_adapter(source: Source) -> SourceAdapter:
    """Адаптер по строке реестра: код, адрес сайта и конфиг адаптера.

    Одна точка для демона и админки: и цикл прогона, и разовые операции (список
    разделов источника, сканирование каталога раздела) создают адаптер одинаково,
    поэтому настройки из `sources.config` действуют везде.
    """
    config = dict(source.config or {})
    options = {
        key: value
        for key, value in config.items()
        # Служебные ключи конфига: адрес передаём отдельно, `boards`/`note` нужны
        # планировщику и админке, а не адаптеру
        if key not in ("base_url", "boards", "note")
    }
    return build_adapter(source.code, base_url=source.base_url or None, **options)


async def ensure_source(
    session: AsyncSession,
    code: str,
    *,
    title: str = "",
    kind: str = "json",
    base_url: str = "",
    config: Optional[Dict[str, Any]] = None,
    is_enabled: bool = False,
    schedule_minutes: Optional[int] = None,
    rate_limit_rps: Optional[float] = None,
    budget_minutes: Optional[int] = None,
    sort_order: Optional[int] = None,
) -> Source:
    """Создаёт источник, если его ещё нет (идемпотентно).

    Первый запуск API/парсера заводит источник из настроек окружения, дальше
    всё (включение, лимиты, конфиг адаптера) правится в админке.
    """
    source = await get_source(session, code)
    if source is not None:
        return source

    source = Source(
        code=code,
        title=title or code,
        kind=kind,
        base_url=base_url,
        config=config or {},
        is_enabled=is_enabled,
        schedule_minutes=30 if schedule_minutes is None else schedule_minutes,
        rate_limit_rps=1.0 if rate_limit_rps is None else rate_limit_rps,
        budget_minutes=30 if budget_minutes is None else budget_minutes,
        sort_order=0 if sort_order is None else sort_order,
    )
    session.add(source)
    await session.flush()
    return source


# ── Журнал прогонов ─────────────────────────────────────────────────


async def start_run(session: AsyncSession, source: Source, phase: str = "catalog") -> ParseRun:
    """Открывает запись о прогоне источника (status=running)."""
    run = ParseRun(source_id=source.id, phase=phase, status="running", stats={})
    session.add(run)
    await session.flush()
    return run


async def finish_run(
    session: AsyncSession,
    run: ParseRun,
    *,
    status: str = "ok",
    stats: Optional[Dict[str, Any]] = None,
    phase: str = "done",
    error: Optional[str] = None,
) -> None:
    """Закрывает прогон: итог, фаза, ошибка (если была)."""
    run.status = status
    run.phase = phase
    run.finished_at = datetime.utcnow()
    if stats:
        # JSONB: складываем сводку поверх текущей (фазы дописывают свои цифры)
        merged = dict(run.stats or {})
        merged.update(stats)
        run.stats = merged
    if error:
        run.error = error[:2000]
    await session.flush()


async def last_runs(session: AsyncSession, source_id: int, limit: int = 5) -> List[ParseRun]:
    """Последние прогоны источника (свежие сверху) — для вкладки источника."""
    result = await session.execute(
        select(ParseRun)
        .where(ParseRun.source_id == source_id)
        .order_by(ParseRun.started_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def close_orphan_runs(
    session: AsyncSession, *, error: str = "прервано перезапуском процесса"
) -> int:
    """Закрывает прогоны, оставшиеся `running` после перезапуска парсера.

    Без этого после каждого рестарта (деплой, перезагрузка) в журнале висел бы
    «вечный» прогон, а в админке показывались бы два активных. Вызывается при
    запуске демона, до первого цикла.
    """
    result = await session.execute(
        update(ParseRun)
        .where(ParseRun.status == "running")
        .values(status="error", error=error[:2000], finished_at=datetime.utcnow())
    )
    await session.commit()
    return int(result.rowcount or 0)
