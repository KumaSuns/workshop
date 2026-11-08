from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtGui import QImage

APP_ROOT = Path(__file__).resolve().parent.parent
_CAPTURES = APP_ROOT / "data" / "captures"
_RECORD = APP_ROOT / "data" / "screens.jsonl"
_SAME_SCREEN_DIFF = 8.9
SCREEN_DIFF_MAX = _SAME_SCREEN_DIFF * 2


def current_screen_name(image: QImage) -> str | None:
    if image.isNull() or not _RECORD.is_file():
        return None
    best_name = ""
    best = None
    for name, path in _registered():
        saved = QImage(str(path))
        if saved.isNull():
            continue
        diff = _diff(image, saved)
        if best is None or diff < best:
            best = diff
            best_name = name
    if best is None or best > SCREEN_DIFF_MAX or not best_name:
        return None
    return best_name


def _registered() -> list[tuple[str, Path]]:
    rows: list[tuple[str, Path]] = []
    for line in _RECORD.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = str(item.get("name") or "").strip()
        file_name = str(item.get("file") or "").strip()
        if not name or not file_name:
            continue
        rows.append((name, _CAPTURES / file_name))
    return rows


def _diff(left: QImage, right: QImage) -> float:
    width, height = 48, 96
    left = left.scaled(width, height).convertToFormat(QImage.Format.Format_RGB32)
    right = right.scaled(width, height).convertToFormat(QImage.Format.Format_RGB32)
    total = 0
    count = width * height * 3
    for y in range(height):
        for x in range(width):
            a = left.pixel(x, y)
            b = right.pixel(x, y)
            total += abs(((a >> 16) & 255) - ((b >> 16) & 255))
            total += abs(((a >> 8) & 255) - ((b >> 8) & 255))
            total += abs((a & 255) - (b & 255))
    return total / count
