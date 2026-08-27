from __future__ import annotations

import colorsys
import json
from pathlib import Path

from PIL import Image

from app.coin_read import _scale_box, boxes_close
from app.data_sync import trainer_data_dir

ITEM_SLOT_KEYS = (
    "score_plus",
    "coin_plus",
    "exp_plus",
    "time_plus",
    "bomb_plus",
    "5to4",
    "combo_plus",
)
TSUM_SLOT_KEY = "used_tsum"
ALL_SLOT_KEYS = ITEM_SLOT_KEYS + (TSUM_SLOT_KEY,)

ITEM_ICON_KEYS = {
    "score_plus": "score",
    "coin_plus": "coin",
    "exp_plus": "exp",
    "time_plus": "time",
    "bomb_plus": "bomb",
    "5to4": "five_to_four",
    "combo_plus": "combo",
}

SLOT_LABELS = {key: key for key in ITEM_SLOT_KEYS}
SLOT_LABELS[TSUM_SLOT_KEY] = "使用ツム"

ITEM_COIN_COST = {
    "score_plus": 500,
    "coin_plus": 500,
    "exp_plus": 500,
    "time_plus": 1000,
    "bomb_plus": 1500,
    "5to4": 1800,
    "combo_plus": 1200,
}

ICON_DIM = 0.28
ICON_ON = 1.0


def item_coin_cost(used: set[str]) -> int:
    return sum(ITEM_COIN_COST.get(slot, 0) for slot in used)


def _slots_path() -> Path:
    return trainer_data_dir() / "item_slots.json"


def _clean_box(box: dict) -> dict[str, int]:
    return {
        "x": int(box["x"]),
        "y": int(box["y"]),
        "w": max(1, int(box["w"])),
        "h": max(1, int(box["h"])),
    }


def crop_box(image: Image.Image, box: dict[str, int]) -> Image.Image:
    left = max(0, int(box["x"]))
    top = max(0, int(box["y"]))
    right = min(image.width, left + max(1, int(box["w"])))
    bottom = min(image.height, top + max(1, int(box["h"])))
    return image.crop((left, top, right, bottom))


def sample_color(image: Image.Image, box: dict[str, int]) -> tuple[int, int, int]:
    crop = crop_box(image.convert("RGB"), box)
    width, height = crop.size
    if width < 2 or height < 2:
        return (0, 0, 0)
    inset_x = max(1, int(width * 0.2))
    inset_y = max(1, int(height * 0.2))
    inner = crop.crop((inset_x, inset_y, width - inset_x, height - inset_y))
    pixels = list(inner.getdata())
    if not pixels:
        pixels = list(crop.getdata())
    count = max(len(pixels), 1)
    red = sum(pixel[0] for pixel in pixels) / count
    green = sum(pixel[1] for pixel in pixels) / count
    blue = sum(pixel[2] for pixel in pixels) / count
    return (int(round(red)), int(round(green)), int(round(blue)))


def yellow_blue_ratios(image: Image.Image, box: dict[str, int]) -> tuple[float, float]:
    crop = crop_box(image.convert("RGB"), box)
    width, height = crop.size
    if width < 2 or height < 2:
        return 0.0, 0.0
    inset_x = max(1, int(width * 0.2))
    inset_y = max(1, int(height * 0.2))
    inner = crop.crop((inset_x, inset_y, width - inset_x, height - inset_y))
    iw, ih = inner.size
    step_x = max(1, iw // 24)
    step_y = max(1, ih // 24)
    pixels = inner.load()
    total = 0
    yellow = 0
    blue = 0
    for yy in range(0, ih, step_y):
        for xx in range(0, iw, step_x):
            red, green, blue_v = pixels[xx, yy][:3]
            hue, sat, val = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue_v / 255.0)
            total += 1
            if 0.10 <= hue <= 0.18 and sat >= 0.30 and val >= 0.35:
                yellow += 1
            elif 0.52 <= hue <= 0.72 and sat >= 0.28 and val >= 0.25:
                blue += 1
    if total <= 0:
        return 0.0, 0.0
    return yellow / total, blue / total


def box_means_used(image: Image.Image, box: dict[str, int]) -> bool:
    yellow, blue = yellow_blue_ratios(image, box)
    return yellow > blue


class ItemSlotStore:
    def __init__(self) -> None:
        self._rows: dict[str, list[tuple[dict[str, int], int, int, tuple[int, int, int] | None]]] = {
            key: [] for key in ALL_SLOT_KEYS
        }
        self.reload()

    def reload(self) -> None:
        self._rows = {key: [] for key in ALL_SLOT_KEYS}
        path = _slots_path()
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        for key in ALL_SLOT_KEYS:
            for item in payload.get(key) or []:
                if not isinstance(item, dict):
                    continue
                box = item.get("box")
                width = int(item.get("width") or 0)
                height = int(item.get("height") or 0)
                if not box or width <= 0 or height <= 0:
                    continue
                color = item.get("color")
                rgb = None
                if isinstance(color, (list, tuple)) and len(color) >= 3:
                    rgb = (int(color[0]), int(color[1]), int(color[2]))
                self._rows[key].append((_clean_box(box), width, height, rgb))

    def _save(self) -> None:
        payload: dict[str, list[dict]] = {key: [] for key in ALL_SLOT_KEYS}
        for key, rows in self._rows.items():
            for box, width, height, color in rows:
                row = {"box": _clean_box(box), "width": int(width), "height": int(height)}
                if color is not None:
                    row["color"] = [int(color[0]), int(color[1]), int(color[2])]
                payload[key].append(row)
        path = _slots_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(
        self,
        key: str,
        box: dict[str, int],
        width: int,
        height: int,
        color: tuple[int, int, int] | None = None,
        persist: bool = True,
    ) -> None:
        if key not in ALL_SLOT_KEYS or width <= 0 or height <= 0:
            return
        cleaned = _clean_box(box)
        rows = self._rows.setdefault(key, [])
        for index, (existing, src_w, src_h, old_color) in enumerate(rows):
            scaled = _scale_box(existing, src_w, src_h, width, height)
            if boxes_close(scaled, cleaned, width, height):
                keep_color = color if color is not None else old_color
                rows[index] = (cleaned, width, height, keep_color)
                if persist:
                    self._save()
                return
        rows.insert(0, (cleaned, width, height, color))
        if persist:
            self._save()

    def box_for(
        self,
        key: str,
        width: int,
        height: int,
        extra: list[tuple[dict[str, int], int, int]] | None = None,
    ) -> dict[str, int] | None:
        rows: list[tuple[dict[str, int], int, int]] = []
        if extra:
            rows.extend(extra)
        for box, src_w, src_h, _color in self._rows.get(key) or []:
            rows.append((box, src_w, src_h))
        if not rows or width <= 0 or height <= 0:
            return None
        aspect = width / max(height, 1)
        box, src_w, src_h = min(rows, key=lambda row: abs(row[1] / max(row[2], 1) - aspect))
        return _scale_box(box, src_w, src_h, width, height)

    def boxes_for(
        self,
        key: str,
        width: int,
        height: int,
        extra: list[tuple[dict[str, int], int, int]] | None = None,
    ) -> list[dict[str, int]]:
        seen: list[dict[str, int]] = []
        rows: list[tuple[dict[str, int], int, int]] = []
        if extra:
            rows.extend(extra)
        for box, src_w, src_h, _color in self._rows.get(key) or []:
            rows.append((box, src_w, src_h))
        for box, src_w, src_h in rows:
            scaled = _scale_box(box, src_w, src_h, width, height)
            if any(boxes_close(scaled, other, width, height) for other in seen):
                continue
            seen.append(scaled)
        return seen

    def colors_for(self, key: str) -> list[tuple[int, int, int]]:
        return [color for _box, _w, _h, color in self._rows.get(key) or [] if color is not None]
