"""COIN はコインの画面、RESULT はリザルトの画面で、内側の盤面の枠を読む。"""
import sys
from pathlib import Path

import torch
from PIL import Image
from torchvision import transforms

WORKSHOP = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKSHOP / "tsumtsum-analyze"))
sys.path.insert(0, str(WORKSHOP / "tsumtsum-analyzer"))

from app.play_coin import (
    _TAUGHT_COIN_900,
    _money_digits,
    _region_box,
    _result_coin_box,
    play_predictor,
)
from tsumtsum_analyze.scene_scan import (
    IMAGENET_MEAN,
    IMAGENET_STD,
    KIND_THRESHOLD,
    SCENE_INPUT,
    _class_score,
    load_scene_checkpoint,
)

_device = torch.device("cpu")
_model, _classes = load_scene_checkpoint(_device)
_transform = transforms.Compose(
    [
        transforms.Resize((SCENE_INPUT, SCENE_INPUT)),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ]
)
play_predictor()

sys.stdout.write("ready\n")
sys.stdout.flush()


def _header(pixels, width: int, y: int):
    x0 = int(width * 0.05)
    x1 = max(x0 + 2, int(width * 0.95))
    xs = []
    for x in range(x0, x1, 2):
        red, green, blue = pixels[x, y]
        if blue > 160 and green > 120 and blue > red + 40:
            xs.append(x)
    samples = max(1, (x1 - x0) // 2)
    if len(xs) < samples * 0.45 or xs[-1] - xs[0] < width * 0.28:
        return None
    return xs[0], xs[-1]


def _board(image: Image.Image) -> Image.Image:
    """写真の再生でゲームが内側にあるときは、その盤面だけにする。"""
    width, height = image.size
    pixels = image.load()
    top = None
    for y in range(int(height * 0.08), int(height * 0.40)):
        if _header(pixels, width, y):
            top = y
            break
    if top is None:
        return image
    bottom = None
    for y in range(int(height * 0.92), int(height * 0.55), -1):
        if _header(pixels, width, y):
            bottom = y
            break
    if bottom is None or bottom - top < height * 0.4:
        return image
    span = None
    best = 0
    for y in range(top, min(bottom, top + max(8, int(height * 0.06)))):
        found = _header(pixels, width, y)
        if found and found[1] - found[0] > best:
            best = found[1] - found[0]
            span = found
    if span is None:
        return image
    left, right = span
    if right - left > width * 0.85:
        return image
    return image.crop((left, top, right + 1, bottom + 1))


def _scene_probs(image: Image.Image):
    tensor = _transform(image).unsqueeze(0)
    with torch.inference_mode():
        return torch.softmax(_model(tensor), dim=1)[0]


def _read(image: Image.Image, key: str) -> str:
    predictor = play_predictor()
    if predictor is None:
        return ""
    if key == "coin" and image.size == (900, 1600):
        box = _TAUGHT_COIN_900
    else:
        box = _region_box(predictor, image, key)
        if key == "result_coin":
            box = _result_coin_box(image, box)
    if not box:
        return ""
    width, height = image.size
    left = max(0, int(box["x"]))
    top = max(0, int(box["y"]))
    right = min(width, left + max(1, int(box["w"])))
    bottom = min(height, top + max(1, int(box["h"])))
    if right - left < 4 or bottom - top < 4:
        return ""
    crop = image.crop((left, top, right, bottom))
    digit_key = "coin" if key == "result_coin" else key
    try:
        raw = str(predictor.predict_coin_digits(crop, digit_key) or "")
    except Exception:
        return ""
    digits = _money_digits(raw)
    if not digits:
        return ""
    return f"{int(digits):,}"


def main() -> None:
    for line in sys.stdin:
        path = line.strip().strip('"')
        coin = ""
        result = ""
        if path:
            try:
                image = _board(Image.open(path).convert("RGB"))
                probs = _scene_probs(image)
                if _class_score(probs, _classes, "coin") >= KIND_THRESHOLD:
                    coin = _read(image, "coin")
                if _class_score(probs, _classes, "result") >= KIND_THRESHOLD:
                    result = _read(image, "result_coin")
            except Exception:
                coin = ""
                result = ""
        sys.stdout.write(f"{coin}\t{result}\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
