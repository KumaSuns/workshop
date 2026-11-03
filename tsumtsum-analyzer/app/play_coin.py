"""オートプレイと同じコインの切り出しと数字の読み。"""

from __future__ import annotations

import sys

from PIL import Image

from app.paths import WORKSHOP_ROOT

_TAUGHT_COIN_900 = {"x": 311, "y": 234, "w": 275, "h": 73}
_SCREEN_ROOT = WORKSHOP_ROOT / "tsumtsum-screen-recognition"
_predictor = None
_predictor_failed = False


def _money_digits(text: str) -> str:
    return "".join(char for char in str(text or "") if char.isdigit()).lstrip("0")


def _result_coin_icon(image) -> tuple[int, int, int, int] | None:
    """リザルトのコインアイコン。星より塗りが濃い金色の円。"""
    scale = 4 if image.width >= 800 else 2
    small = image.resize(
        (max(1, image.width // scale), max(1, image.height // scale)),
        Image.Resampling.BOX,
    )
    width, height = small.size
    pixels = small.load()
    mask = []
    for y in range(height):
        row = []
        for x in range(width):
            red, green, blue = pixels[x, y][:3]
            row.append(red > 175 and green > 110 and blue < 140 and red > green - 15 and red > blue + 40)
        mask.append(row)
    seen = [[False] * width for _ in range(height)]
    best = None
    for y in range(height):
        for x in range(width):
            if not mask[y][x] or seen[y][x]:
                continue
            stack = [(x, y)]
            seen[y][x] = True
            count = 0
            min_x = max_x = x
            min_y = max_y = y
            while stack:
                cx, cy = stack.pop()
                count += 1
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < width and 0 <= ny < height and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            if count < 12:
                continue
            box_w = max_x - min_x + 1
            box_h = max_y - min_y + 1
            fill = count / (box_w * box_h)
            icon_w, icon_h = box_w * scale, box_h * scale
            icon_x, icon_y = min_x * scale, min_y * scale
            if icon_w < image.width * 0.035 or icon_w > image.width * 0.09:
                continue
            if not 0.75 <= icon_w / max(icon_h, 1) <= 1.35:
                continue
            center_y = (icon_y + icon_h / 2) / image.height
            if not 0.42 <= center_y <= 0.68:
                continue
            if fill < 0.68:
                continue
            if best is None or fill > best[0]:
                best = (fill, icon_x, icon_y, icon_w, icon_h)
    if best is None:
        return None
    return best[1], best[2], best[3], best[4]


def _result_coin_box(image, model_box: dict[str, int] | None) -> dict[str, int] | None:
    icon = _result_coin_icon(image)
    if icon is None:
        return model_box
    icon_x, icon_y, icon_w, icon_h = icon
    width, height = image.size
    left = max(0, int(icon_x - 0.85 * icon_w))
    top = max(0, int(icon_y + icon_h / 2 - 1.08 * icon_w))
    box_w = min(width - left, int(round(icon_w * 9.0)))
    box_h = min(height - top, int(round(icon_w * 2.15)))
    row = {"x": left, "y": top, "w": max(1, box_w), "h": max(1, box_h)}
    if not model_box:
        return row
    box_left = int(model_box["x"])
    box_top = int(model_box["y"])
    box_width = int(model_box["w"])
    box_height = int(model_box["h"])
    center_x = icon_x + icon_w / 2
    center_y = icon_y + icon_h / 2
    inside = box_left <= center_x <= box_left + box_width and box_top <= center_y <= box_top + box_height
    if inside and box_height <= icon_w * 2.6:
        return model_box
    return row


def _region_box(predictor, rgb, key: str) -> dict[str, int] | None:
    models = getattr(predictor, "models", None) or {}
    model = models.get(key)
    transform = getattr(predictor, "_transform", None)
    if model is None or transform is None or rgb is None:
        return None
    image = rgb if getattr(rgb, "mode", "") == "RGB" else rgb.convert("RGB")
    tensor = transform(image).unsqueeze(0).to(predictor.device)
    return predictor._decode(model, tensor, image.size[0], image.size[1])


def _read_coin_key(predictor, rgb, boxes: dict[str, dict[str, int]] | None, key: str) -> str:
    if rgb is None:
        return ""
    predict = getattr(predictor, "predict_coin_digits", None)
    if predict is None:
        return ""
    if key == "coin" and rgb.size == (900, 1600):
        box = _TAUGHT_COIN_900
    else:
        if not boxes:
            return ""
        box = boxes.get(key)
        if key == "result_coin":
            box = _result_coin_box(rgb, box)
    if not box:
        return ""
    width, height = rgb.size
    left = max(0, int(box["x"]))
    top = max(0, int(box["y"]))
    right = min(width, left + max(1, int(box["w"])))
    bottom = min(height, top + max(1, int(box["h"])))
    if right - left < 4 or bottom - top < 4:
        return ""
    crop = rgb.crop((left, top, right, bottom))
    digit_key = "coin" if key == "result_coin" else key
    try:
        raw = str(predict(crop, digit_key) or "")
    except Exception:
        return ""
    return "".join(char for char in raw if char.isdigit())


def _load_screen_predictor():
    hidden = {
        key: sys.modules.pop(key)
        for key in list(sys.modules)
        if key == "app" or key.startswith("app.")
    }
    root = str(_SCREEN_ROOT)
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    predictor = None
    keep: dict[str, object] = {}
    try:
        from app.predictor import Predictor

        predictor = Predictor(_SCREEN_ROOT / "data" / "models")
        keep = {
            key: sys.modules[key]
            for key in list(sys.modules)
            if key == "app" or key.startswith("app.")
        }
        predictor._trainer_modules = keep
        return predictor
    except Exception:
        return None
    finally:
        if added:
            try:
                sys.path.remove(root)
            except ValueError:
                pass
        for key in list(sys.modules):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]
        sys.modules.update(hidden)
        if predictor is not None:
            predictor._trainer_modules = keep


def reset_play_predictor() -> None:
    global _predictor, _predictor_failed
    _predictor = None
    _predictor_failed = False


def play_predictor():
    global _predictor, _predictor_failed
    if _predictor is not None or _predictor_failed:
        return _predictor
    predictor = _load_screen_predictor()
    if predictor is None or not getattr(predictor, "digit_models", None):
        _predictor_failed = True
        return None
    _predictor = predictor
    return predictor


_timer_digit_reader = None


def _read_timer_digits():
    global _timer_digit_reader
    if _timer_digit_reader is not None:
        return _timer_digit_reader
    import importlib.util

    path = WORKSHOP_ROOT / "tsumtsum-autoplay" / "app" / "timer_digits.py"
    spec = importlib.util.spec_from_file_location("autoplay_timer_digits", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _timer_digit_reader = module.read_timer_digits
    return _timer_digit_reader


def read_play_timer(rgb, box: dict[str, int] | None = None) -> tuple[int | None, dict[str, int] | None]:
    predictor = play_predictor()
    if predictor is None or rgb is None:
        return None, box
    image = rgb if getattr(rgb, "mode", "") == "RGB" else rgb.convert("RGB")
    if box is None:
        box = _region_box(predictor, image, "timer")
    if not box:
        return None, None
    width, height = image.size
    left = max(0, int(box["x"]))
    top = max(0, int(box["y"]))
    right = min(width, left + max(1, int(box["w"])))
    bottom = min(height, top + max(1, int(box["h"])))
    if right - left < 4 or bottom - top < 4:
        return None, box
    crop = image.crop((left, top, right, bottom))
    value = _timer_value(crop)
    if value is None:
        from PIL import ImageOps

        value = _timer_value(ImageOps.autocontrast(crop, cutoff=2))
    if value is None:
        return None, box
    return value, box


def _timer_value(crop) -> int | None:
    reader = _read_timer_digits()
    if reader is None:
        return None
    try:
        text = reader(crop)
    except Exception:
        return None
    digits = "".join(char for char in str(text or "") if char.isdigit())
    if not digits:
        return None
    value = int(digits)
    if value > 180:
        return None
    return value


def read_play_coin(rgb, key: str) -> str:
    predictor = play_predictor()
    if predictor is None or rgb is None:
        return ""
    if key == "coin" and rgb.size == (900, 1600):
        boxes = None
    else:
        box = _region_box(predictor, rgb, key)
        boxes = {key: box} if box else None
    digits = _money_digits(_read_coin_key(predictor, rgb, boxes, key))
    if not digits:
        return ""
    return f"{int(digits):,}"
