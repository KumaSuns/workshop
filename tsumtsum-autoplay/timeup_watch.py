"""ゲーム画面を窓から見て、TIME UP だけを知らせる。マウスは動かさない。"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

from PIL import Image
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent
SCREEN = ROOT.parent / "tsumtsum-screen-recognition"
TIMEUP_SCORE = 0.70
SCENE_KIND_SCORE = 0.18


def _load_scene():
    path = SCREEN / "app" / "scene_model.py"
    spec = importlib.util.spec_from_file_location("timeup_scene_model", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scene_file() -> Path | None:
    bundled = SCREEN / "data" / "models" / "scene.pt"
    if bundled.is_file():
        return bundled
    other = ROOT.parent / "video-frame-extractor" / "scene.pt"
    if other.is_file():
        return other
    return None


def _portrait(image: Image.Image) -> Image.Image:
    width, height = image.size
    if width <= height:
        return image
    sample_w = min(160, width)
    sample_h = max(1, int(round(height * sample_w / width)))
    sample = image.resize((sample_w, sample_h))
    left_s = 0
    while left_s < sample_w - 1 and _column_luma(sample, left_s) < 14:
        left_s += 1
    right_s = sample_w - 1
    while right_s > left_s and _column_luma(sample, right_s) < 14:
        right_s -= 1
    scale = width / sample_w
    left = int(left_s * scale)
    right = min(width, int((right_s + 1) * scale))
    if right - left < height * 0.35:
        strip_w = max(1, int(height * 9 / 16))
        left = max(0, (width - strip_w) // 2)
        right = min(width, left + strip_w)
    return image.crop((left, 0, right, height))


def _column_luma(image: Image.Image, x: int) -> float:
    height = image.size[1]
    total = 0.0
    for y in range(height):
        red, green, blue = image.getpixel((x, y))[:3]
        total += 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return total / max(height, 1)


def _rgb(image: QImage) -> Image.Image | None:
    if image.isNull():
        return None
    converted = image.convertToFormat(QImage.Format.Format_RGB888)
    width = converted.width()
    height = converted.height()
    stride = converted.bytesPerLine()
    ptr = converted.constBits()
    size = converted.sizeInBytes()
    try:
        buf = bytes(memoryview(ptr)[:size])
    except TypeError:
        buf = bytes(ptr[:size])
    if stride == width * 3:
        return Image.frombytes("RGB", (width, height), buf)
    rows = [buf[row * stride : row * stride + width * 3] for row in range(height)]
    return Image.frombytes("RGB", (width, height), b"".join(rows))


def _load_module(name: str, filename: str):
    path = SCREEN / "app" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scene_top(model, transform, classes, image: Image.Image) -> tuple[str, float, bool]:
    import torch

    view = _portrait(image)
    tensor = transform(view).unsqueeze(0)
    with torch.no_grad():
        probs = torch.softmax(model(tensor), dim=1)[0]
    index = int(probs.argmax().item())
    name = classes[index] if 0 <= index < len(classes) else "other"
    score = float(probs[index].item())
    if "timeup" in classes:
        timeup_index = classes.index("timeup")
    elif int(probs.numel()) >= 3:
        timeup_index = 2
    else:
        timeup_index = -1
    timeup = False
    if 0 <= timeup_index < int(probs.numel()):
        timeup_score = float(probs[timeup_index].item())
        timeup = index == timeup_index and timeup_score >= TIMEUP_SCORE
    scores = {
        classes[i]: float(probs[i].item())
        for i in range(min(len(classes), int(probs.numel())))
    }
    return name, score, timeup, scores


def _load_coin_readers():
    model_mod = _load_module("timeup_region_model", "model.py")
    digit_mod = _load_module("timeup_digit_model", "digit_model.py")
    hud_mod = _load_module("timeup_hud_number", "hud_number.py")
    if model_mod is None or digit_mod is None or hud_mod is None:
        return None
    import torch
    from torchvision import transforms

    models_dir = SCREEN / "data" / "models"
    device = torch.device("cpu")
    region_transform = transforms.Compose(
        [
            transforms.Resize((model_mod.INPUT_SIZE, model_mod.INPUT_SIZE)),
            transforms.ToTensor(),
            transforms.Normalize(model_mod.IMAGENET_MEAN, model_mod.IMAGENET_STD),
        ]
    )
    digit_transform = transforms.Compose(
        [
            transforms.Resize((digit_mod.DIGIT_HEIGHT, digit_mod.DIGIT_WIDTH)),
            transforms.ToTensor(),
            transforms.Normalize(digit_mod.IMAGENET_MEAN, digit_mod.IMAGENET_STD),
        ]
    )
    regions = {}
    digits = {}
    for key, filename in (("coin", "coin.pt"), ("result_coin", "result_coin.pt")):
        path = models_dir / filename
        if not path.is_file():
            continue
        checkpoint = torch.load(path, map_location=device, weights_only=False)
        model = model_mod.GameRegionNet(pretrained=False)
        state = checkpoint["state_dict"] if isinstance(checkpoint, dict) and "state_dict" in checkpoint else checkpoint
        try:
            model.load_state_dict(state)
        except Exception:
            continue
        model.eval()
        regions[key] = model
    for key, filename in (("coin", "coin_digits.pt"), ("result_coin", "result_coin_digits.pt")):
        path = models_dir / filename
        if not path.is_file():
            continue
        checkpoint = torch.load(path, map_location=device, weights_only=False)
        model = digit_mod.CoinDigitNet(pretrained=False)
        state = checkpoint["state_dict"] if isinstance(checkpoint, dict) and "state_dict" in checkpoint else checkpoint
        try:
            model.load_state_dict(state)
        except Exception:
            continue
        model.eval()
        digits[key] = model
    if "coin" in digits and "result_coin" not in digits:
        digits["result_coin"] = digits["coin"]
    if not regions or not digits:
        return None
    return regions, digits, region_transform, digit_transform, digit_mod, hud_mod


def _read_money(readers, image: Image.Image, key: str) -> str:
    if readers is None or key not in readers[0] or key not in readers[1]:
        return ""
    import torch

    regions, digits, region_transform, digit_transform, digit_mod, hud_mod = readers
    width, height = image.size
    tensor = region_transform(image).unsqueeze(0)
    with torch.no_grad():
        x, y, w, h = regions[key](tensor)[0].tolist()
    left = max(0, min(int(round(x * width)), width - 1))
    top = max(0, min(int(round(y * height)), height - 1))
    right = min(width, left + max(1, int(round(w * width))))
    bottom = min(height, top + max(1, int(round(h * height))))
    if right - left < 4 or bottom - top < 4:
        return ""
    crop = image.crop((left, top, right, bottom))
    prepared = hud_mod.prepare_digit_crop(crop, key)
    with torch.no_grad():
        logits = digits[key](digit_transform(prepared.convert("RGB")).unsqueeze(0))
    text = digit_mod.decode_logits(logits.cpu())
    if key == "coin":
        text = hud_mod.adjust_coin_digits(prepared, text)
    return "".join(char for char in str(text or "") if char.isdigit())


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    del app
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.bluestacks import capture_window_frame

    scene = _load_scene()
    weight = _scene_file()
    if scene is None or weight is None:
        return
    import torch
    from torchvision import transforms

    checkpoint = torch.load(weight, map_location="cpu", weights_only=False)
    classes = tuple(checkpoint.get("classes") or scene.SCENE_CLASSES) if isinstance(checkpoint, dict) else scene.SCENE_CLASSES
    model = scene.SceneNet(pretrained=False, num_classes=len(classes))
    state = checkpoint["state_dict"] if isinstance(checkpoint, dict) and "state_dict" in checkpoint else checkpoint
    try:
        model.load_state_dict(state)
    except Exception:
        return
    model.eval()
    transform = transforms.Compose(
        [
            transforms.Resize((scene.SCENE_INPUT, scene.SCENE_INPUT)),
            transforms.ToTensor(),
            transforms.Normalize(scene.IMAGENET_MEAN, scene.IMAGENET_STD),
        ]
    )
    while True:
        frame = capture_window_frame()
        rgb = None if frame is None else _rgb(frame)
        if rgb is not None:
            _name, _score, timeup, _scores = _scene_top(model, transform, classes, rgb)
            if timeup:
                print("TIMEUP", flush=True)
                time.sleep(0.3)
                continue
        time.sleep(0.35)


if __name__ == "__main__":
    main()
