"""Safe image handling.

Fixes several real defects in the original app:
  * No decompression-bomb guard (a crafted PNG/JPEG could exhaust memory).
  * EXIF orientation ignored (phone photos render sideways).
  * ``Image.open`` consumed the upload stream without ``seek(0)``.
  * No error handling for corrupt / non-image files.

All heavy lifting lives here so the UI and the AI layer share one hardened path.
"""
from __future__ import annotations

import base64
import io
from typing import Tuple

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    _HEIF_OK = True
except Exception:  # pragma: no cover - optional dependency
    _HEIF_OK = False


class ImageError(ValueError):
    """Raised when an upload cannot be safely decoded into an image."""


def heif_supported() -> bool:
    return _HEIF_OK


def load_image(data: bytes, max_pixels: int = 60_000_000) -> Image.Image:
    """Decode raw bytes into an upright RGB image, guarding against bombs.

    Raises ``ImageError`` on anything that is not a safe, decodable image. The
    decompression-bomb guard is enforced by checking the declared dimensions from
    the header *before* decoding pixels, so it is thread-safe (no mutation of the
    process-global ``Image.MAX_IMAGE_PIXELS`` — important under Streamlit's
    threaded reruns).
    """
    if not data:
        raise ImageError("Empty file.")

    # 1) Cheap structural verification + dimension check on a throwaway copy.
    try:
        probe = Image.open(io.BytesIO(data))
        w, h = probe.size  # from the header — no pixel decode yet
        if w * h > max_pixels:
            raise ImageError("Image is too large to process safely.")
        probe.verify()  # checks headers/CRC without decoding pixels
    except ImageError:
        raise
    except Image.DecompressionBombError as exc:
        raise ImageError("Image is too large to process safely.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageError("File is not a valid or supported image.") from exc

    # 2) verify() leaves the image unusable -> reopen for real decode.
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)  # respect phone orientation
        img.load()
    except Image.DecompressionBombError as exc:
        raise ImageError("Image is too large to process safely.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ImageError("File could not be decoded.") from exc

    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def _downscale(img: Image.Image, max_dim: int) -> Image.Image:
    w, h = img.size
    longest = max(w, h)
    if longest <= max_dim:
        return img
    scale = max_dim / float(longest)
    return img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)


def to_jpeg_b64(img: Image.Image, max_dim: int = 1600, quality: int = 85) -> Tuple[str, str]:
    """Downscale + encode as base64 JPEG for the Claude vision API.

    Returns ``(base64_data, media_type)``.
    """
    small = _downscale(img.convert("RGB"), max_dim)
    buf = io.BytesIO()
    small.save(buf, format="JPEG", quality=quality)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"


def thumbnail_bytes(img: Image.Image, max_dim: int = 420, quality: int = 80) -> bytes:
    """A small JPEG suitable for the history list."""
    small = _downscale(img.convert("RGB"), max_dim)
    buf = io.BytesIO()
    small.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def encode_jpeg(img: Image.Image, max_dim: int = 1600, quality: int = 88) -> bytes:
    """A reasonably-sized JPEG for archival in the history store."""
    small = _downscale(img.convert("RGB"), max_dim)
    buf = io.BytesIO()
    small.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
