# src/parsers/__init__.py
"""Адаптеры источников: реестр «код источника → класс адаптера».

Новый источник = адаптер (контракт в `base.py`) + запись в таблице `sources`:
цикл прогона, очередь, конвейер файла и админка уже умеют работать с любым
источником из этого реестра.
"""
from typing import Dict, Type

from src.parsers.base import CatalogResult, FileNode, SourceAdapter, ThreadNode
from src.parsers.dvach import DvachAdapter
from src.parsers.slivach import SlivachAdapter

ADAPTERS: Dict[str, Type] = {
    "dvach": DvachAdapter,
    "slivach": SlivachAdapter,
}


def build_adapter(code: str, **options) -> SourceAdapter:
    """Создаёт адаптер по коду источника из реестра (`sources.code`)."""
    adapter_cls = ADAPTERS.get(code)
    if adapter_cls is None:
        raise ValueError(f"Нет адаптера для источника «{code}» (см. src/parsers/__init__.py)")
    return adapter_cls(**options)


__all__ = [
    "ADAPTERS",
    "CatalogResult",
    "DvachAdapter",
    "FileNode",
    "SourceAdapter",
    "ThreadNode",
    "build_adapter",
]
