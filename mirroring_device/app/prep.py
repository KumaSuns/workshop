from __future__ import annotations

import colorsys
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

WORKSHOP = Path(__file__).resolve().parents[2]
_SLOTS_PATH = WORKSHOP / "tsumtsum-screen-recognition" / "data" / "item_slots.json"
_MODELS = WORKSHOP / "video-frame-extractor" / "app" / "assets" / "models" / "use_tsum"
_KEYS = (
    "score_plus",
    "coin_plus",
    "exp_plus",
    "time_plus",
    "bomb_plus",
    "5to4",
    "combo_plus",
)
_FALLBACK = (
    (135.0 / 1320, 1232.0 / 2868, 239.0 / 1320, 247.0 / 2868),
    (412.0 / 1320, 1236.0 / 2868, 239.0 / 1320, 247.0 / 2868),
    (679.0 / 1320, 1237.0 / 2868, 239.0 / 1320, 247.0 / 2868),
    (942.0 / 1320, 1240.0 / 2868, 239.0 / 1320, 247.0 / 2868),
    (131.0 / 1320, 1571.0 / 2868, 239.0 / 1320, 247.0 / 2868),
    (402.0 / 1320, 1576.0 / 2868, 239.0 / 1320, 247.0 / 2868),
    (679.0 / 1320, 1571.0 / 2868, 239.0 / 1320, 247.0 / 2868),
)
_SEEN = 0.28
_FACE = (700 / 900, 1320 / 1600, 100 / 900, 90 / 1600)
_slots: tuple[tuple[float, float, float, float], ...] | None = None
_names: dict[str, str] | None = None
_prototypes: list[tuple[str, str, list[list[float]]]] | None = None


def read_prep(image: QImage) -> tuple[bool, str, list[bool]]:
    off = [False] * len(_KEYS)
    if image.width() < 8 or image.height() <= image.width():
        return False, "", off
    frame = image.convertToFormat(QImage.Format.Format_RGB32)
    seen = 0
    for index, slot in enumerate(_slot_boxes()):
        yellow, blue = _slot_color(frame, slot)
        if yellow + blue < _SEEN:
            continue
        seen += 1
        off[index] = yellow > blue
    if seen < 5:
        return False, "", [False] * len(_KEYS)
    return True, _match_name(frame), off


def _slot_boxes() -> tuple[tuple[float, float, float, float], ...]:
    global _slots
    if _slots is not None:
        return _slots
    loaded = list(_FALLBACK)
    try:
        payload = json.loads(_SLOTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _slots = tuple(loaded)
        return _slots
    for index, key in enumerate(_KEYS):
        rows = payload.get(key) or []
        if not rows or not isinstance(rows[0], dict):
            continue
        item = rows[0]
        box = item.get("box") or {}
        width = float(item.get("width") or 0)
        height = float(item.get("height") or 0)
        if width < 1 or height < 1:
            continue
        loaded[index] = (
            float(box.get("x") or 0) / width,
            float(box.get("y") or 0) / height,
            float(box.get("w") or 0) / width,
            float(box.get("h") or 0) / height,
        )
    _slots = tuple(loaded)
    return _slots


def _slot_color(image: QImage, slot: tuple[float, float, float, float]) -> tuple[float, float]:
    width = image.width()
    height = image.height()
    x = int(round(slot[0] * width))
    y = int(round(slot[1] * height))
    box_w = max(1, int(round(slot[2] * width)))
    box_h = max(1, int(round(slot[3] * height)))
    x = min(max(x, 0), width - 1)
    y = min(max(y, 0), height - 1)
    box_w = min(box_w, width - x)
    box_h = min(box_h, height - y)
    inset_x = max(1, int(box_w * 0.2))
    inset_y = max(1, int(box_h * 0.2))
    left = x + inset_x
    top = y + inset_y
    right = x + box_w - inset_x
    bottom = y + box_h - inset_y
    if right <= left or bottom <= top:
        return 0.0, 0.0
    step_x = max(1, (right - left) // 24)
    step_y = max(1, (bottom - top) // 24)
    total = yellow = blue = 0
    for yy in range(top, bottom, step_y):
        for xx in range(left, right, step_x):
            red, green, blue_v = _rgb(image, xx, yy)
            hue, sat, val = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue_v / 255.0)
            total += 1
            if 0.10 <= hue <= 0.18 and sat >= 0.30 and val >= 0.35:
                yellow += 1
            elif 0.52 <= hue <= 0.72 and sat >= 0.28 and val >= 0.25:
                blue += 1
    if total == 0:
        return 0.0, 0.0
    return yellow / total, blue / total


def _match_name(image: QImage) -> str:
    _load_faces()
    assert _prototypes is not None
    if not _prototypes:
        return ""
    feature = _feature(_crop_face(image))
    best: dict[str, tuple[float, str]] = {}
    for tsum_id, name, rows in _prototypes:
        dist = min(_l1(feature, row) for row in rows)
        held = best.get(tsum_id)
        if held is None or dist < held[0]:
            best[tsum_id] = (dist, name)
    first = float("inf")
    second = float("inf")
    found = ""
    for dist, name in best.values():
        if dist < first:
            second = first
            first = dist
            found = name
        elif dist < second:
            second = dist
    if first == float("inf") or first >= 0.08 or first * 2 >= second:
        return ""
    return found


def _crop_face(image: QImage) -> QImage:
    width = image.width()
    height = image.height()
    if width < 400 or height < 700:
        return image
    nx, ny, nw, nh = _FACE
    left = min(max(int(nx * width), 0), width - 1)
    top = min(max(int(ny * height), 0), height - 1)
    right = max(left + 1, min(int((nx + nw) * width), width))
    bottom = max(top + 1, min(int((ny + nh) * height), height))
    return image.copy(left, top, right - left, bottom - top)


def _feature(crop: QImage) -> list[float]:
    color = crop.scaled(18, 18, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    color = color.convertToFormat(QImage.Format.Format_RGB32)
    hue_bins = [0.0] * 18
    sat_bins = [0.0] * 8
    val_bins = [0.0] * 8
    for y in range(18):
        for x in range(18):
            red, green, blue = _rgb(color, x, y)
            hue, sat, val = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
            hue_bins[min(17, max(0, int(hue * 18)))] += 1.0
            sat_bins[min(7, max(0, int(sat * 8)))] += 1.0
            val_bins[min(7, max(0, int(val * 8)))] += 1.0
    total = 18.0 * 18.0
    values = [value / total for value in hue_bins + sat_bins + val_bins]
    gray = crop.scaled(14, 14, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    gray = gray.convertToFormat(QImage.Format.Format_RGB32)
    luma: list[float] = []
    for y in range(14):
        for x in range(14):
            red, green, blue = _rgb(gray, x, y)
            luma.append((0.299 * red + 0.587 * green + 0.114 * blue) / 255.0)
    mean = sum(luma) / len(luma)
    values.extend(value - mean for value in luma)
    return values


def _load_faces() -> None:
    global _names, _prototypes
    if _prototypes is not None:
        return
    names: dict[str, str] = {}
    try:
        payload = json.loads((_MODELS / "registry.json").read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            names = {str(key): str(value) for key, value in payload.items()}
    except (OSError, json.JSONDecodeError):
        names = {}
    rows: list[tuple[str, str, list[list[float]]]] = []
    if _MODELS.is_dir():
        for folder in sorted(path for path in _MODELS.iterdir() if path.is_dir()):
            model = folder / "model.json"
            if not model.is_file():
                continue
            try:
                payload = json.loads(model.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            feats = [list(map(float, row)) for row in payload.get("prototypes") or [] if isinstance(row, list)]
            if feats:
                rows.append((folder.name, names.get(folder.name, folder.name), feats))
    _names = names
    _prototypes = rows


def _l1(left: list[float], right: list[float]) -> float:
    count = min(len(left), len(right))
    if count <= 0:
        return float("inf")
    return sum(abs(left[index] - right[index]) for index in range(count)) / count


def _rgb(image: QImage, x: int, y: int) -> tuple[int, int, int]:
    pixel = image.pixel(x, y)
    return (pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255
