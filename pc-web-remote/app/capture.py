from __future__ import annotations

import io

import mss
from PIL import Image


def grab_jpeg(max_width: int = 1280, quality: int = 55) -> bytes:
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        raw = sct.grab(monitor)
    image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    width, height = image.size
    if width > max_width:
        height = max(1, int(round(height * max_width / width)))
        image = image.resize((max_width, height), Image.Resampling.BILINEAR)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def virtual_screen() -> tuple[int, int, int, int]:
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        return (
            int(monitor["left"]),
            int(monitor["top"]),
            int(monitor["width"]),
            int(monitor["height"]),
        )
