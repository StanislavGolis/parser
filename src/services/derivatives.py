# src/services/derivatives.py
"""Генерация деривативов для оптимизации трафика.

- Фото: thumb (WebP ~400px, q75), thumb_blur (размытый превью для премиума), web (WebP ~1600px, q80).
- Видео: poster (кадр 400px, JPEG) + его размытая версия, web 720p (H.264 + faststart), длительность.

Все операции синхронные (CPU/ffmpeg) — вызывать через asyncio.to_thread.
"""
import asyncio
import io
import subprocess
from pathlib import Path
from typing import Dict, Optional

from PIL import Image, ImageFilter

THUMB_MAX = 400
WEB_MAX = 1600
THUMB_QUALITY = 75
WEB_QUALITY = 80
VIDEO_WEB_HEIGHT = 720
POSTER_MAX = 400
# Размытый превью премиум-контента: сильно уменьшаем и размываем → очень лёгкий WebP
BLUR_MAX = 48
BLUR_RADIUS = 8
BLUR_QUALITY = 60


def _resize_webp(img: Image.Image, max_side: int, quality: int) -> bytes:
    im = img.copy()
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=quality, method=4)
    return buf.getvalue()


def _normalize(img: Image.Image) -> Image.Image:
    if img.mode in ("P", "PA"):
        return img.convert("RGBA")
    if img.mode not in ("RGB", "RGBA", "L"):
        return img.convert("RGB")
    return img


def build_blur_webp(img: Image.Image) -> bytes:
    """Размытый превью: уменьшение до BLUR_MAX + GaussianBlur → лёгкий WebP.

    Публично отдаётся вместо реального превью премиум-файла: форму кадра
    видно, содержимое — нет.
    """
    im = _normalize(img).copy()
    im.thumbnail((BLUR_MAX, BLUR_MAX), Image.LANCZOS)
    im = im.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
    if im.mode != "RGB":
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=BLUR_QUALITY, method=4)
    return buf.getvalue()


def build_blur_from_bytes(data: bytes) -> bytes:
    """Размытый превью из байтов изображения (используется для postера видео)."""
    return build_blur_webp(Image.open(io.BytesIO(data)))


def build_image_variants(data: bytes) -> Dict[str, bytes]:
    """thumb + thumb_blur + web (WebP). Бросает исключение, если файл битый."""
    img = _normalize(Image.open(io.BytesIO(data)))
    return {
        "thumb": _resize_webp(img, THUMB_MAX, THUMB_QUALITY),
        "thumb_blur": build_blur_webp(img),
        "web": _resize_webp(img, WEB_MAX, WEB_QUALITY),
    }


def probe_duration(path: Path) -> Optional[float]:
    """Длительность видео в секундах (ffprobe), либо None."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        val = (r.stdout or "").strip()
        return float(val) if val else None
    except Exception:
        return None


def build_poster(path: Path) -> Optional[bytes]:
    """Кадр-превью видео (JPEG, до 400px по ширине)."""
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-ss", "1", "-i", str(path),
                "-frames:v", "1", "-vf", f"scale='min({POSTER_MAX},iw)':-2",
                "-f", "image2pipe", "-vcodec", "mjpeg", "-",
            ],
            capture_output=True,
            timeout=180,
        )
        return r.stdout or None
    except Exception:
        return None


def build_video_web(src: Path, dst: Path) -> bool:
    """Оптимизированная версия видео: 720p H.264 (faststart, без апскейла)."""
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error", "-i", str(src),
                "-vf", f"scale=-2:'min({VIDEO_WEB_HEIGHT},ih)'",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
                str(dst),
            ],
            check=True,
            timeout=3600,
        )
        return dst.exists() and dst.stat().st_size > 0
    except Exception:
        return False


async def generate_and_upload(
    uploader,
    *,
    base_key: str,
    media_type: str,
    local_path: Path,
    file_data: Optional[bytes] = None,
):
    """Строит деривативы и загружает их через uploader.

    Возвращает (variants: dict|None, duration_seconds: float|None).
    variants = {"thumb": key, "thumb_blur": key, "web"|"video": key} —
    превью, размытое превью (для премиума) и полная версия.
    """
    local_path = Path(local_path)
    variants: Dict[str, str] = {}
    duration: Optional[float] = None

    if media_type == "image":
        data = file_data if file_data is not None else local_path.read_bytes()
        built = await asyncio.to_thread(build_image_variants, data)
        for kind, payload in built.items():
            key = f"{base_key}_{kind}.webp"
            if await uploader.upload_bytes(payload, key, "image/webp"):
                variants[kind] = key
    else:
        duration = await asyncio.to_thread(probe_duration, local_path)
        poster = await asyncio.to_thread(build_poster, local_path)
        if poster:
            key = f"{base_key}_poster.jpg"
            if await uploader.upload_bytes(poster, key, "image/jpeg"):
                variants["thumb"] = key
            try:
                blur = await asyncio.to_thread(build_blur_from_bytes, poster)
                blur_key = f"{base_key}_poster_blur.webp"
                if await uploader.upload_bytes(blur, blur_key, "image/webp"):
                    variants["thumb_blur"] = blur_key
            except Exception:  # noqa: BLE001
                pass  # без блюра премиум-превью отдаст обычный poster (клиент добларит)
        web_path = local_path.with_name(f"{local_path.stem}_v720.mp4")
        ok = await asyncio.to_thread(build_video_web, local_path, web_path)
        if ok:
            key = f"{base_key}_v720.mp4"
            if await uploader.upload_file(web_path, key, content_type="video/mp4"):
                variants["video"] = key
            web_path.unlink(missing_ok=True)

    return (variants or None), duration
