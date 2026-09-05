import hashlib
import io
from typing import Optional, Tuple
from PIL import Image
import mimetypes  # Вместо magic

from src.core.config import settings


class MediaValidator:
    """Валидация и фильтрация медиафайлов"""
    
    # Минимальные размеры
    MIN_IMAGE_SIZE = 50 * 1024      # 50 KB
    MIN_VIDEO_SIZE = 1 * 1024 * 1024  # 1 MB
    MIN_IMAGE_DIMENSION = 200       # 200x200 пикселей
    
    @classmethod
    def validate(cls, file_data: bytes, filename: str) -> Tuple[bool, Optional[str], Optional[dict]]:
        """Полная валидация файла"""
        # 1. Проверка размера
        size_valid, error = cls._check_size(file_data, filename)
        if not size_valid:
            return False, error, None
        
        # 2. Определение типа по расширению
        file_type = cls._determine_type_by_extension(filename)
        if not file_type:
            return False, f"Неподдерживаемое расширение: {filename}", None
        
        # 3. Дополнительная проверка для изображений
        metadata = {}
        if file_type == 'image':
            is_valid, error, img_meta = cls._validate_image(file_data)
            if not is_valid:
                return False, error, None
            metadata.update(img_meta)
        
        metadata['file_type'] = file_type
        return True, None, metadata
    
    @classmethod
    def _check_size(cls, file_data: bytes, filename: str) -> Tuple[bool, Optional[str]]:
        """Проверка размера файла"""
        size = len(file_data)
        ext = filename.split('.')[-1].lower() if '.' in filename else ''
        image_exts = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'}
        video_exts = {'mp4', 'webm', 'mkv', 'avi', 'mov'}
        
        if ext in image_exts:
            if size < cls.MIN_IMAGE_SIZE:
                return False, f"Изображение слишком маленькое: {size} байт (мин. {cls.MIN_IMAGE_SIZE})"
        elif ext in video_exts:
            if size < cls.MIN_VIDEO_SIZE:
                return False, f"Видео слишком маленькое: {size} байт (мин. {cls.MIN_VIDEO_SIZE})"
        else:
            return False, f"Неизвестное расширение: {ext}"
        
        return True, None
    
    @classmethod
    def _determine_type_by_extension(cls, filename: str) -> Optional[str]:
        """Определение типа по расширению"""
        ext = filename.split('.')[-1].lower() if '.' in filename else ''
        image_exts = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'}
        video_exts = {'mp4', 'webm', 'mkv', 'avi', 'mov'}
        
        if ext in image_exts:
            return 'image'
        elif ext in video_exts:
            return 'video'
        return None
    
    @classmethod
    def _validate_image(cls, file_data: bytes) -> Tuple[bool, Optional[str], Optional[dict]]:
        """Дополнительная проверка изображений"""
        try:
            img = Image.open(io.BytesIO(file_data))
            width, height = img.size
            
            if width < cls.MIN_IMAGE_DIMENSION or height < cls.MIN_IMAGE_DIMENSION:
                return False, f"Изображение слишком маленькое: {width}x{height} (мин. {cls.MIN_IMAGE_DIMENSION}x{cls.MIN_IMAGE_DIMENSION})", None
            
            return True, None, {
                'width': width,
                'height': height,
                'format': img.format
            }
            
        except Exception as e:
            return False, f"Ошибка проверки изображения: {e}", None
    
    @classmethod
    def is_duplicate(cls, file_data: bytes, existing_hash: Optional[str] = None) -> Tuple[bool, str]:
        """Проверка дубликата по SHA-256"""
        file_hash = hashlib.sha256(file_data).hexdigest()
        if existing_hash and file_hash == existing_hash:
            return True, file_hash
        return False, file_hash