# src/services/media_cache.py
"""Локальный дисковый кэш объектов S3 (LRU по объёму).

Замеры на прод-сервере: S3 у провайдера отдаёт ~3 МБ/с (параллельно ~8 МБ/с),
локальный SSD — 500+ МБ/с. Поэтому всё, что уже прочитано (или скачано парсером),
держим на диске: повторные запросы обслуживаются локально, а трафик чтения из S3
стремится к нулю.

Как устроено:
- ключ объекта (`s3_key`, например `board_16/thread_1/42.jpg`) → файл
  `<dir>/objects/<key>`;
- «свежесть» файла — его mtime, он обновляется при каждом чтении из кэша;
- когда суммарный размер превышает `MEDIA_CACHE_MAX_BYTES` (или на диске остаётся
  меньше `MEDIA_CACHE_MIN_FREE_BYTES`), удаляются самые старые файлы;
- кэш — расходник: первоисточник остаётся в S3, бэкап кэша не нужен.
"""
import asyncio
import os
import shutil
import time
from pathlib import Path
from typing import Dict, Optional

from src.core.config import settings

# Как часто (в секундах) имеет смысл пересчитывать размер кэша при работе.
SWEEP_MIN_INTERVAL = 300.0
# Какую долю от лимита оставляем после чистки (чтобы не чистить на каждом запросе).
SWEEP_TARGET_RATIO = 0.9


class MediaCache:
    """Дисковый кэш: чтение с обновлением «свежести», запись атомарная, LRU-чистка."""

    def __init__(
        self,
        directory: Optional[str] = None,
        max_bytes: Optional[int] = None,
    ) -> None:
        self.directory = Path(directory or settings.MEDIA_CACHE_DIR)
        self.max_bytes = int(
            max_bytes if max_bytes is not None else settings.MEDIA_CACHE_MAX_BYTES
        )
        self.min_free_bytes = int(settings.MEDIA_CACHE_MIN_FREE_BYTES)
        self.enabled = bool(settings.MEDIA_CACHE_ENABLED and self.max_bytes > 0)
        self.objects_dir = self.directory / "objects"

        # Статистика за время жизни процесса (видна в админке)
        self.hits = 0
        self.misses = 0
        self.stored = 0
        self.evicted_bytes = 0
        self.evicted_files = 0

        self._dirty = False
        self._last_sweep = 0.0

        if self.enabled:
            try:
                self.objects_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.enabled = False
                print(f"   [cache] Кэш выключен: {exc}")

    # ───────────────────────── Пути и чтение ─────────────────────────

    def path_for(self, key: str) -> Path:
        """Путь файла кэша для ключа объекта (защита от выхода из каталога)."""
        safe = key.lstrip("/").replace("..", "_")
        return self.objects_dir / safe

    def get(self, key: str) -> Optional[Path]:
        """Возвращает путь в кэше, если файл есть (и обновляет его «свежесть»)."""
        if not self.enabled:
            return None
        path = self.path_for(key)
        if not path.is_file():
            self.misses += 1
            return None
        now = time.time()
        try:
            os.utime(path, (now, now))
        except OSError:
            pass
        self.hits += 1
        return path

    def has(self, key: str) -> bool:
        """Есть ли файл в кэше (без учёта статистики попаданий)."""
        return bool(self.enabled and self.path_for(key).is_file())

    # ───────────────────────── Запись ─────────────────────────

    def store_path(self, key: str, source: Path, move: bool = False) -> Optional[Path]:
        """Кладёт готовый файл в кэш (атомарно через `.part`).

        `move=True` — файл-источник удаляется. Так делает парсер: он всё равно
        удалял скачанный оригинал после выгрузки в S3, теперь тот остаётся в кэше.
        """
        if not self.enabled:
            return None
        source = Path(source)
        if not source.is_file():
            return None
        dest = self.path_for(key)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        temp = dest.with_name(dest.name + ".part")
        try:
            if move:
                try:
                    os.replace(source, temp)
                except OSError:
                    shutil.copyfile(source, temp)
                    source.unlink(missing_ok=True)
            else:
                shutil.copyfile(source, temp)
            os.replace(temp, dest)
        except OSError as exc:
            print(f"   [cache] не удалось положить {key}: {exc}")
            temp.unlink(missing_ok=True)
            return None
        self.stored += 1
        self._dirty = True
        return dest

    def store_bytes(self, key: str, data: bytes) -> Optional[Path]:
        """Кладёт байты (деривативы строятся в памяти) в кэш."""
        if not self.enabled or not data:
            return None
        dest = self.path_for(key)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            temp = dest.with_name(dest.name + ".part")
            temp.write_bytes(data)
            os.replace(temp, dest)
        except OSError as exc:
            print(f"   [cache] не удалось положить {key}: {exc}")
            return None
        self.stored += 1
        self._dirty = True
        return dest

    def path_for_part(self, key: str) -> Path:
        """Путь временного файла для потоковой записи (tee при чтении из S3)."""
        dest = self.path_for(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        return dest.with_name(dest.name + ".part")

    def commit_part(self, key: str, temp: Path) -> Optional[Path]:
        """Завершает потоковую запись: `.part` → финальный файл."""
        if not self.enabled:
            return None
        dest = self.path_for(key)
        try:
            os.replace(temp, dest)
        except OSError as exc:
            print(f"   [cache] не удалось завершить запись {key}: {exc}")
            return None
        self.stored += 1
        self._dirty = True
        return dest

    def drop_part(self, temp: Optional[Path]) -> None:
        """Убирает незавершённый `.part` (клиент прервал запрос и т.п.)."""
        if temp is None:
            return
        try:
            Path(temp).unlink(missing_ok=True)
        except OSError:
            pass

    # ───────────────────── Чистка и статистика ─────────────────────

    def _collect(self, clean_parts: bool = False):
        """Собирает (mtime, size, path) по всем файлам кэша.

        `clean_parts=True` попутно удаляет «зависшие» `.part` (прерванный запрос
        или перезапуск процесса) — они не считаются данными кэша.
        """
        entries = []
        total = 0
        cutoff = time.time() - 3600
        for root, _dirs, files in os.walk(self.objects_dir):
            for name in files:
                path = Path(root) / name
                if name.endswith(".part"):
                    if clean_parts:
                        try:
                            if path.stat().st_mtime < cutoff:
                                path.unlink()
                        except OSError:
                            pass
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                entries.append((stat.st_mtime, stat.st_size, path))
                total += stat.st_size
        return entries, total

    def stats(self) -> Dict[str, object]:
        """Текущее состояние кэша: файлы, объём, лимит, свободное место, счётчики."""
        if self.enabled:
            entries, total = self._collect()
            usage = shutil.disk_usage(self.directory)
        else:
            entries, total, usage = [], 0, shutil.disk_usage(".")
        percent = round(total / self.max_bytes * 100, 1) if self.max_bytes else 0.0
        return {
            "enabled": self.enabled,
            "dir": str(self.directory),
            "files": len(entries),
            "bytes": total,
            "max_bytes": self.max_bytes,
            "min_free_bytes": self.min_free_bytes,
            "used_percent": percent,
            "disk_total": usage.total,
            "disk_free": usage.free,
            "hits": self.hits,
            "misses": self.misses,
            "stored": self.stored,
            "evicted_files": self.evicted_files,
            "evicted_bytes": self.evicted_bytes,
        }

    def sweep(self, force: bool = False) -> int:
        """LRU-чистка: удаляет самые старые файлы, пока бюджет не восстановится.

        Вызывается периодически (после записей) и вручную из админки. Возвращает
        число освобождённых байт.
        """
        if not self.enabled:
            return 0
        now = time.monotonic()
        if not force and not self._dirty and now - self._last_sweep < SWEEP_MIN_INTERVAL:
            return 0

        entries, total = self._collect(clean_parts=True)
        self._dirty = False
        self._last_sweep = now

        usage = shutil.disk_usage(self.directory)
        target = int(self.max_bytes * SWEEP_TARGET_RATIO)
        must_free = max(0, total - target)
        if usage.free < self.min_free_bytes:
            must_free = max(must_free, self.min_free_bytes - usage.free)
        if must_free <= 0:
            return 0

        entries.sort(key=lambda item: item[0])  # старые — первыми
        freed = 0
        removed = 0
        for _mtime, size, path in entries:
            if freed >= must_free:
                break
            try:
                path.unlink()
            except OSError:
                continue
            freed += size
            removed += 1
        if removed:
            self.evicted_bytes += freed
            self.evicted_files += removed
            print(
                f"   [cache] LRU-чистка: удалено {removed} файлов, "
                f"{freed / 1024**2:.0f} МБ"
            )
        return freed

    def clear(self) -> int:
        """Полностью очищает кэш (возвращает число удалённых файлов)."""
        if not self.enabled:
            return 0
        entries, _total = self._collect()
        removed = 0
        for _mtime, _size, path in entries:
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        self._dirty = False
        return removed


class CachingUploader:
    """Обёртка над загрузчиком в S3: тем же вызовом кладёт данные в локальный кэш.

    Парсер и так держит файл в руках (оригинал скачан, деривативы построены в
    памяти), поэтому кэш наполняется «бесплатно» — без обратного скачивания из S3.
    """

    def __init__(self, uploader, cache: MediaCache) -> None:
        self._uploader = uploader
        self._cache = cache

    async def upload_file(self, local_path, remote_key: str, content_type=None):
        stored = await self._uploader.upload_file(
            local_path, remote_key, content_type=content_type
        )
        if stored:
            await asyncio.to_thread(self._cache.store_path, remote_key, Path(local_path))
        return stored

    async def upload_bytes(self, data: bytes, remote_key: str, content_type=None):
        stored = await self._uploader.upload_bytes(data, remote_key, content_type=content_type)
        if stored:
            await asyncio.to_thread(self._cache.store_bytes, remote_key, data)
        return stored


_CACHE: Optional[MediaCache] = None


def get_media_cache() -> MediaCache:
    """Синглтон кэша (общий для API и парсера внутри процесса)."""
    global _CACHE
    if _CACHE is None:
        _CACHE = MediaCache()
    return _CACHE

