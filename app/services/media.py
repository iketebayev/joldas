"""Файлы гида: фото профиля, сканы для верификации (зашифрованы), видеовизитки."""
import io
import secrets
import shutil
from pathlib import Path

from ..config import KYC_KEY, MEDIA_DIR

ROOT = Path(MEDIA_DIR)
KYC = ROOT / "kyc"          # только зашифрованные файлы, наружу не отдаются
PHOTOS = ROOT / "photos"
VIDEOS = ROOT / "videos"

VIDEO_TYPES = {"video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov"}


class BadFile(ValueError):
    pass


def token() -> str:
    return secrets.token_urlsafe(12)


def _fernet():
    from cryptography.fernet import Fernet
    if not KYC_KEY:
        raise RuntimeError("KYC_KEY не задан в .env")
    return Fernet(KYC_KEY.encode())


def clean_image(data: bytes, max_side: int) -> bytes:
    """Проверяет, что это картинка, поворачивает по EXIF и пересохраняет в JPEG без метаданных
    (в EXIF телефона бывают GPS-координаты)."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise BadFile("image") from e
    if min(img.size) < 200:
        raise BadFile("small")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=86, optimize=True)
    return out.getvalue()


def profile_photo(data: bytes) -> bytes:
    """Фото профиля — квадрат по центру, 600 px."""
    from PIL import Image, ImageOps
    img = Image.open(io.BytesIO(clean_image(data, 1600)))
    img = ImageOps.fit(img, (600, 600), centering=(0.5, 0.35))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=86, optimize=True)
    return out.getvalue()


# --- сканы верификации ---------------------------------------------------------------

def kyc_save(data: bytes) -> str:
    KYC.mkdir(parents=True, exist_ok=True)
    name = token() + ".bin"
    (KYC / name).write_bytes(_fernet().encrypt(data))
    return name


def kyc_read(name: str) -> bytes:
    return _fernet().decrypt((KYC / Path(name).name).read_bytes())


def kyc_delete(*names) -> None:
    for n in names:
        if n:
            (KYC / Path(n).name).unlink(missing_ok=True)


# --- фото профиля --------------------------------------------------------------------

def photo_save(data: bytes) -> str:
    PHOTOS.mkdir(parents=True, exist_ok=True)
    name = token() + ".jpg"
    (PHOTOS / name).write_bytes(data)
    return name


def photo_path(name: str) -> Path:
    return PHOTOS / Path(name).name


def photo_delete(name: str | None) -> None:
    if name:
        photo_path(name).unlink(missing_ok=True)


# --- видео ---------------------------------------------------------------------------

def video_dir(tok: str) -> Path:
    return VIDEOS / Path(tok).name


def video_delete(tok: str) -> None:
    shutil.rmtree(video_dir(tok), ignore_errors=True)
