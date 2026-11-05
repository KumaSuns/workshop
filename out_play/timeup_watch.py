"""ゲーム画面を窓から見て、TIME UP と盤面の取り込みを行う。マウスは動かさない。"""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path
from queue import Empty, Queue

from PIL import Image
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent
SCREEN = ROOT / "bundled" / "screen"
TIMEUP_SCORE = 0.70
SCENE_KIND_SCORE = 0.18
_grab_queue: Queue = Queue()
_board_tools: dict[str, object] = {"predictor": None, "save": None}


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


def _look(model, transform, classes, image: Image.Image) -> str:
    import torch

    view = _portrait(image)
    tensor = transform(view).unsqueeze(0)
    with torch.no_grad():
        probs = torch.softmax(model(tensor), dim=1)[0]
    best_name = ""
    best_score = 0.0
    for index, kind in enumerate(classes):
        if index >= int(probs.numel()):
            break
        kind_score = float(probs[index].item())
        if kind == "other" or kind_score <= best_score:
            continue
        best_name = kind
        best_score = kind_score
    if best_name in ("coin", "result") and best_score >= SCENE_KIND_SCORE:
        return "ended"
    if "timeup" in classes:
        timeup_index = classes.index("timeup")
    elif int(probs.numel()) >= 3:
        timeup_index = 2
    else:
        timeup_index = -1
    if 0 <= timeup_index < int(probs.numel()):
        timeup_score = float(probs[timeup_index].item())
        if int(probs.argmax().item()) == timeup_index and timeup_score >= TIMEUP_SCORE:
            return "timeup"
    return ""


def _emit(line: str) -> None:
    sys.stdout.buffer.write((line + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def _read_commands() -> None:
    while True:
        raw = sys.stdin.buffer.readline()
        if not raw:
            return
        text = raw.decode("utf-8", "replace").strip()
        if not text.startswith("GRAB"):
            continue
        parts = text.split("\t")
        name = parts[1] if len(parts) > 1 else ""
        named = len(parts) > 2 and parts[2] == "1"
        limit = int(parts[3]) if len(parts) > 3 and parts[3].lstrip("-").isdigit() else 0
        _grab_queue.put((name, named, limit))


def _grab_board(capture, name: str, named: bool, limit: int) -> None:
    try:
        if _board_tools["predictor"] is None:
            from app.trainer_bridge import load_play_tools, save_play_board

            predictor, _chain, _gap = load_play_tools()
            _board_tools["predictor"] = predictor
            _board_tools["save"] = save_play_board
        predictor = _board_tools["predictor"]
        save = _board_tools["save"]
        if named:
            path = Path(predictor.models_dir) / "named_tsum_test.pt"
            if not predictor.use_named_tsum_model(path):
                _emit("GRAB_FAIL")
                return
            prepare = getattr(predictor, "prepare_named", None)
            if prepare is not None and name:
                prepare(int(limit or 0), name)
        frame = capture()
        rgb = None if frame is None else _rgb(frame)
        if frame is None or frame.isNull() or rgb is None:
            _emit("GRAB_FAIL")
            return
        boxes = predictor.predict_all(Path("."), rgb=rgb)
        game = boxes.get("game") if isinstance(boxes, dict) else None
        pieces = []
        if game is not None:
            pieces = predictor.predict_pieces(Path("."), game, rgb=rgb, inner=False) or []
        ok = save(
            predictor,
            frame,
            game,
            boxes=boxes if isinstance(boxes, dict) else None,
            pieces=pieces,
            rgb=rgb,
        )
        if ok:
            _emit("GRABBED " + name)
        else:
            _emit("GRAB_FAIL")
    except Exception:
        _emit("GRAB_FAIL")


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
    threading.Thread(target=_read_commands, daemon=True).start()
    transform = transforms.Compose(
        [
            transforms.Resize((scene.SCENE_INPUT, scene.SCENE_INPUT)),
            transforms.ToTensor(),
            transforms.Normalize(scene.IMAGENET_MEAN, scene.IMAGENET_STD),
        ]
    )
    money_on = False
    while True:
        try:
            job = _grab_queue.get_nowait()
        except Empty:
            job = None
        if job is not None:
            _grab_board(capture_window_frame, *job)
        frame = capture_window_frame()
        rgb = None if frame is None else _rgb(frame)
        label = "" if rgb is None else _look(model, transform, classes, rgb)
        if label == "ended":
            if not money_on:
                print("ENDED", flush=True)
            money_on = True
            time.sleep(0.3)
            continue
        money_on = False
        if label == "timeup":
            print("TIMEUP", flush=True)
            time.sleep(0.3)
        else:
            time.sleep(0.35)


if __name__ == "__main__":
    main()
