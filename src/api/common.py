# src/api/common.py
"""Общие константы и хелперы публичных роутов API."""
from typing import Iterable

from src.api.schemas import MediaOut
from src.core.models import Media
from src.services.b2_uploader import B2Uploader

# Базовый фильтр публичного показа файла.
VISIBLE_FILTER = (
    Media.is_visible.is_(True),
    Media.is_active.is_(True),
    Media.duplicate_of_id.is_(None),
)


def sign_media_urls(
    items: list[MediaOut],
    sources: Iterable[Media],
    b2: B2Uploader,
) -> list[MediaOut]:
    """Прикрепляет подписанные URL B2 к элементам списка (для галерей).

    Подписывание выполняется локально (без сетевых вызовов) и не требует
    повторного запроса к API на каждый файл.
    """
    for item, source in zip(items, sources):
        if source.b2_key:
            item.url = b2.generate_presigned_url(source.b2_key)
    return items
