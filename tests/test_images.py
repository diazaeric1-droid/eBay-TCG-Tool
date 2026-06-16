"""Image hardening: bomb guard, corrupt files, EXIF, thumbnails."""
import io

import pytest
from PIL import Image

from tcg.images import ImageError, encode_jpeg, load_image, thumbnail_bytes, to_jpeg_b64


def _png_bytes(w=120, h=80, color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def test_loads_valid_image():
    img = load_image(_png_bytes())
    assert img.size == (120, 80)
    assert img.mode == "RGB"


def test_rejects_corrupt_file():
    with pytest.raises(ImageError):
        load_image(b"this is definitely not an image")


def test_rejects_empty_file():
    with pytest.raises(ImageError):
        load_image(b"")


def test_decompression_bomb_guard():
    data = _png_bytes(200, 200)        # 40_000 px
    with pytest.raises(ImageError):
        load_image(data, max_pixels=4_000)   # 40_000 > 2 * 4_000 -> bomb error


def test_to_jpeg_b64_downscales():
    img = load_image(_png_bytes(2000, 1000))
    b64, media = to_jpeg_b64(img, max_dim=400)
    assert media == "image/jpeg"
    assert len(b64) > 100
    # decode back and confirm long edge was capped
    import base64
    out = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert max(out.size) == 400


def test_thumbnail_and_encode():
    img = load_image(_png_bytes(1000, 1000))
    thumb = thumbnail_bytes(img, max_dim=200)
    assert thumb[:2] == b"\xff\xd8"     # JPEG SOI marker
    big = encode_jpeg(img, max_dim=800)
    assert max(Image.open(io.BytesIO(big)).size) == 800
