# src/main.py
"""Демон парсинга: цикл по источникам контента.

Каждый источник (2ch, сайты) — свой адаптер (`src/parsers/`), своя очередь и свои
флаги прогона (`parser:{code}:enabled|up|alive|current|progress`), поэтому один
источник можно остановить, не трогая остальные. Общее — план обхода и очередь
(`services/scan_planner.py`), конвейер файла (`services/pipeline.py`), реестр
источников и журнал прогонов (`services/sources.py`).

Каждый прогон источника открывает запись в `parse_runs` и закрывает её итогом:
`ok` (цикл дошёл до конца), `stopped` (остановили кнопкой в админке), `error`.
"""
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.config import settings
from src.core.models import Source
from src.core.redis_client import redis_client
from src.parsers import ADAPTERS, build_adapter
from src.services import sources as sources_service
from src.services.scan_planner import ScanPlanner

HEARTBEAT_INTERVAL = 15  # секунд между обновлениями ключей живости
# Какой источник обслуживает этот процесс. Пусто — все включённые источники
# (удобно локально); в проде у каждого источника свой контейнер:
# `PARSER_SOURCE=dvach` / `PARSER_SOURCE=slivach` (см. docker-compose.prod.yml).
ONLY_SOURCE = (os.getenv("PARSER_SOURCE") or "").strip() or None
# Доски источника из окружения (историческая настройка 2ch; у сайтов список досок
# живёт в `sources.config["boards"]`)
ENV_BOARDS = {"dvach": settings.BOARDS_TO_PARSE}

# Текущая доска каждого источника — читается heartbeat-таском
CURRENT_BOARD: Dict[str, Optional[str]] = {}


async def init_db():
    """Создаёт движок и фабрику async-сессий.

    Схема БД управляется Alembic (`alembic upgrade head`); create_all не используется.
    """
    engine = create_async_engine(settings.DATABASE_URL, echo=settings.SQL_ECHO, future=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return async_session


async def heartbeat_loop(async_session) -> None:
    """Держит ключи живости каждого источника (`parser:{code}:up|alive|current`).

    Источники читаются из реестра: источник, который сейчас на паузе, не считается
    «живым», а его текущий раздел снимается — админка показывает правду.
    """
    try:
        while True:
            try:
                async with async_session() as session:
                    for source in await sources_service.list_sources(session):
                        running = await sources_service.is_enabled(source.code)
                        await sources_service.heartbeat(
                            source.code,
                            running=running,
                            current=CURRENT_BOARD.get(source.code) if running else None,
                        )
                        # Пока идёт прогон, освежаем метку прогресса: админка не
                        # должна решать, что парсер «завис», если долго качается
                        # один большой файл (см. touch_progress).
                        if running:
                            await sources_service.touch_progress(source.code)
            except Exception as exc:  # noqa: BLE001 — heartbeat не должен падать
                print(f"[warn] heartbeat: {exc}")
            await asyncio.sleep(HEARTBEAT_INTERVAL)
    except asyncio.CancelledError:
        pass


async def run_source_cycle(session: AsyncSession, source: Source) -> dict:
    """Один цикл прогона источника: каталоги → очередь → докачка по очереди.

    Возвращает статистику прогона (для `parse_runs` и лога). Источник, у которого
    случилась ошибка, не роняет остальные: исключение ловится вызывающим кодом,
    прогон закрывается статусом `error`.
    """
    print(f"\n[run] Источник {source.code} ({source.title or source.code}): цикл начат")
    config = source.config if isinstance(source.config, dict) else {}
    # Опции адаптера приходят из реестра (`sources.config`): базовый URL, отбор
    # записей, селекторы/пагинация у сайтов. Тот же конструктор используют
    # админка (список разделов, сканирование каталога) — настройки одни на всех.
    adapter = sources_service.build_source_adapter(source)
    planner = ScanPlanner(
        session,
        adapter,
        source.code,
        source_id=source.id,
        stop_check=lambda: _stopped(source.code),
    )
    run = await sources_service.start_run(session, source)
    await session.commit()

    stats: dict = {
        "boards": 0,
        "queued": 0,
        "threads_done": 0,
        "threads_failed": 0,
        "files_saved": 0,
        "stopped": False,
    }
    status = "ok"
    error_text: Optional[str] = None

    await adapter.__aenter__()
    try:
        # Доски, заданные конфигурацией источника (только при первом запуске):
        # у 2ch это BOARDS_TO_PARSE, у сайтов — `sources.config["boards"]`,
        # а если и его нет — список разделов по умолчанию из адаптера
        slugs = (
            ENV_BOARDS.get(source.code)
            or list(config.get("boards") or [])
            or list(getattr(adapter, "default_boards", []) or [])
        )
        if slugs:
            await planner.ensure_configured_boards([str(slug) for slug in slugs])

        # Фаза A: каталоги всех парсируемых досок источника → очередь в БД
        plan = await planner.build_scan_plan()
        stats["queued"] = len(plan)
        started = datetime.utcnow()
        budget = int(source.budget_minutes or settings.PARSE_CYCLE_BUDGET_MINUTES)

        # Фаза B: докачка по очереди (свежие изменения → LRU), с бюджетом цикла
        for done, (board_slug, thread_id, reason) in enumerate(plan, start=1):
            if await _stopped(source.code):
                print(f"[stop] Источник {source.code}: остановлен командой из админки")
                stats["stopped"] = True
                status = "stopped"
                break
            if budget > 0 and (datetime.utcnow() - started).total_seconds() >= budget * 60:
                print(
                    f"[budget] Источник {source.code}: цикл идёт больше {budget} мин — "
                    f"остаток очереди ({len(plan) - done + 1}) в следующем цикле"
                )
                break
            CURRENT_BOARD[source.code] = board_slug
            ok = await planner.scan_thread(board_slug, thread_id, reason)
            stats["threads_done" if ok else "threads_failed"] += 1
        CURRENT_BOARD[source.code] = None
    except Exception as exc:  # noqa: BLE001 — один источник не роняет остальные
        status = "error"
        error_text = f"{type(exc).__name__}: {exc}"
        print(f"[err] Источник {source.code}: цикл прерван — {error_text}")
        await session.rollback()
    finally:
        CURRENT_BOARD[source.code] = None
        try:
            await adapter.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
        try:
            await sources_service.clear_progress(source.code)
            await sources_service.finish_run(
                session, run, status=status, stats=stats, error=error_text
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] Источник {source.code}: журнал прогона не записан ({exc})")

    print(
        f"[done] Источник {source.code}: статус {status}, "
        f"в очереди {stats['queued']}, тредов обработано {stats['threads_done']}, "
        f"с ошибками {stats['threads_failed']}"
    )
    return stats


async def _stopped(code: str) -> bool:
    """Прогон источника остановлен кнопкой в админке (свой флаг у каждого)."""
    return not await sources_service.is_enabled(code)



async def _source_can_run(source: Source) -> bool:
    """Источник включён в реестре и запущен кнопкой (`parser:{code}:enabled`)."""
    if not source.is_enabled:
        return False
    return await sources_service.is_enabled(source.code)


def sources_for_run(all_sources: List[Source]) -> Tuple[List[Source], List[str]]:
    """Отбирает источники для этого процесса.

    Возвращает (источники к прогону, коды источников без адаптера). Фильтр
    `PARSER_SOURCE` — это и есть «контейнер на источник»: процесс трогает только
    свой источник, поэтому прогоны не мешают друг другу. Без `PARSER_SOURCE`
    (локальная разработка) обслуживаются все источники, у которых есть адаптер.
    """
    candidates = [s for s in all_sources if ONLY_SOURCE is None or s.code == ONLY_SOURCE]
    ready = [s for s in candidates if s.code in ADAPTERS]
    unknown = [s.code for s in candidates if s.code not in ADAPTERS]
    return ready, unknown


async def main() -> None:
    role = f"источник {ONLY_SOURCE}" if ONLY_SOURCE else "все включённые источники"
    print(f"[run] Запуск парсера-демона ({role})...")
    print(f"[dir] Хранилище: {settings.STORAGE_PATH}")
    print("[info] Парсинг управляется из админки: у каждого источника своя кнопка")
    print("-" * 50)

    async_session = await init_db()
    last_reconcile: Optional[datetime] = None
    warned_unknown = False

    # Гигиена журнала: прогоны, оборванные прошлым перезапуском, не должны висеть
    async with async_session() as session:
        closed = await sources_service.close_orphan_runs(session)
        if closed:
            print(f"[init] Закрыто незавершённых прогонов прошлого запуска: {closed}")

    heartbeat_task = asyncio.create_task(heartbeat_loop(async_session))

    try:
        while True:
            try:
                async with async_session() as session:
                    all_sources = await sources_service.list_sources(session)

                ready, unknown = sources_for_run(all_sources)
                if unknown and not warned_unknown:
                    # Адаптера нет — этап разработки источника: контейнер простаивает
                    print(
                        f"[warn] Нет адаптера для источника: {', '.join(unknown)} "
                        f"(см. src/parsers/__init__.py) — простаиваю"
                    )
                    warned_unknown = True
                if ONLY_SOURCE and not ready:
                    print(
                        f"[pause] Источник {ONLY_SOURCE} не описан в реестре "
                        f"(или у него нет адаптера) — жду настройки в админке..."
                    )
                    await asyncio.sleep(30)
                    continue

                enabled = [s for s in ready if await _source_can_run(s)]
                if not enabled:
                    # На паузе: ничего не парсим, ждём кнопку в админке
                    last_reconcile = None  # при запуске снова сделаем сверку
                    print(
                        f"[pause] Нет запущенных источников ({role}) — жду команды из админки..."
                    )
                    await asyncio.sleep(5)
                    continue

                # Прогоны независимы: у каждого источника своя сессия и свои флаги,
                # ошибка одного не мешает остальным (см. run_source_cycle).
                for source in enabled:
                    if not await _source_can_run(source):
                        continue
                    async with async_session() as session:
                        await run_source_cycle(session, source)

                # Сверка данных (общая: БД ↔ локальный кэш ↔ S3). Её выполняет ровно
                # один контейнер: у «своего» источника RECONCILE_MINUTES >= 0,
                # у остальных −1 (см. docker-compose.prod.yml).
                if settings.RECONCILE_MINUTES >= 0:
                    due = last_reconcile is None or (
                        settings.RECONCILE_MINUTES > 0
                        and (datetime.utcnow() - last_reconcile).total_seconds() / 60
                        >= settings.RECONCILE_MINUTES
                    )
                    if due:
                        source = enabled[0]
                        async with async_session() as session:
                            adapter = build_adapter(
                                source.code, base_url=source.base_url or None
                            )
                            planner = ScanPlanner(
                                session, adapter, source.code, source_id=source.id
                            )
                            await adapter.__aenter__()
                            try:
                                await planner.run_reconciliation()
                            finally:
                                await adapter.__aexit__(None, None, None)
                        last_reconcile = datetime.utcnow()

                print(f"\n[wait] Ожидание {settings.PARSE_INTERVAL} секунд до следующего цикла...\n")
                await asyncio.sleep(settings.PARSE_INTERVAL)

            except KeyboardInterrupt:
                raise
            except Exception as e:  # noqa: BLE001 — демон не должен умирать
                print(f"[err] Критическая ошибка: {e}")
                await asyncio.sleep(5)  # Пауза перед перезапуском
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except (asyncio.CancelledError, Exception):
            pass
        # Закрываем Redis-пул: иначе при остановке процесса redis-py ругается
        # «Event loop is closed» в AbstractConnection.__del__
        try:
            await redis_client.aclose()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[bye] Остановка парсера...")

