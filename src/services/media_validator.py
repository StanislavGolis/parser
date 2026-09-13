# src/services/media_validator.py
import hashlib
import io
from typing import Optional, Tuple

from PIL import Image


class MediaValidator:
    """Валидация и фильтрация медиафайлов (вторая линия, после метаданных API)."""

    IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
    VIDEO_EXTS = {"mp4", "webm", "mkv"}
    ALLOWED_EXTS = IMAGE_EXTS | VIDEO_EXTS

    # Минимальные размеры в байтах
    MIN_IMAGE_SIZE = 50 * 1024        # 50 КБ
    MIN_VIDEO_SIZE = 1 * 1024 * 1024  # 1 МБ
    MIN_IMAGE_DIMENSION = 200         # 200x200 px

    @classmethod
    def classify(cls, filename: str) -> Optional[str]:
        """Возвращает 'image' | 'video' | None по расширению."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext in cls.IMAGE_EXTS:
            return "image"
        if ext in cls.VIDEO_EXTS:
            return "video"
        return None

    @classmethod
    def is_allowed(cls, filename, size_bytes, media_type, width=None, height=None) -> Tuple[bool, Optional[str]]:
        """Проверка по размерам и разрешению (метаданные из API, до скачивания)."""
        mtype = cls.classify(filename)
        if mtype is None or mtype != media_type:
            return False, "тип файла не совпадает с расширением"

        min_size = cls.MIN_IMAGE_SIZE if media_type == "image" else cls.MIN_VIDEO_SIZE
        # Размер может быть неизвестен (сайты без метаданных): 0/None — «не знаем»,
        # по весу не режем, реальная проверка идёт после скачивания (Pillow/SHA-256)
        if size_bytes and size_bytes < min_size:
            return False, f"слишком маленький файл: {size_bytes} байт (мин. {min_size})"

        if media_type == "image" and width and height:
            if width < cls.MIN_IMAGE_DIMENSION or height < cls.MIN_IMAGE_DIMENSION:
                return False, f"маленькое разрешение: {width}x{height} (мин. {cls.MIN_IMAGE_DIMENSION})"

        return True, None

    # ---------- Хеши и целостность ----------

    @classmethod
    def compute_md5(cls, data: bytes) -> str:
        return hashlib.md5(data).hexdigest()

    @classmethod
    def compute_sha256(cls, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @classmethod
    def verify_integrity(cls, data: bytes, expected_md5: str) -> bool:
        """Файл скачан полностью и md5 совпадает с API."""
        if not data:
            return False
        return cls.compute_md5(data) == expected_md5

    @classmethod
    def verify_image(cls, data: bytes) -> Tuple[bool, Optional[str]]:
        """Изображение открывается (битые/пустые файлы отсекаются)."""
        try:
            img = Image.open(io.BytesIO(data))
            img.verify()
            return True, None
        except Exception as e:
            return False, f"битый файл: {e}"