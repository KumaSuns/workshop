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
SCREEN = ROOT / "bundled" / "screen"
TIMEUP_SCORE = 0.70


def _load_scene():
    path = SCREEN / "app" / "scene_model.py"
    spec = importlib.util.spec_from_file_location("timeup_scene_model", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scene_file() -> Path | None:
    app_model = ROOT / "models" / "scene.pt"
    if app_model.is_file():
        return app_model
    bundled = SCREEN / "data" / "models" / "scene.pt"
    if bundled.is_file():
        return bundled
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


def _seen(model, transform, classes, image: Image.Image) -> bool:
    import torch

    view = _portrait(image)
    tensor = transform(view).unsqueeze(0)
    with torch.no_grad():
        probs = torch.softmax(model(tensor), dim=1)[0]
    if "timeup" in classes:
        index = classes.index("timeup")
    elif int(probs.numel()) >= 3:
        index = 2
    else:
        return False
    if index < 0 or index >= int(probs.numel()):
        return False
    score = float(probs[index].item())
    top = int(probs.argmax().item()) == index
    return top and score >= TIMEUP_SCORE


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
        if rgb is not None and _seen(model, transform, classes, rgb):
            print("TIMEUP", flush=True)
            time.sleep(0.3)
        else:
            time.sleep(0.35)


if __name__ == "__main__":
    main()
