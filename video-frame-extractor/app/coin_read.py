from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import torch
from PIL import Image
from torchvision import transforms

from app.data_sync import trainer_data_dir

TSUM_APP = Path(__file__).resolve().parents[2] / "tsumtsum-screen-recognition" / "app"
INPUT_SIZE = 224
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def _load(alias: str, filename: str):
    if alias in sys.modules:
        return sys.modules[alias]
    path = TSUM_APP / filename
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


def _scale_box(box: dict, src_w: int, src_h: int, dst_w: int, dst_h: int) -> dict[str, int]:
    sx = dst_w / max(src_w, 1)
    sy = dst_h / max(src_h, 1)
    x = int(round(int(box["x"]) * sx))
    y = int(round(int(box["y"]) * sy))
    w = max(1, int(round(int(box["w"]) * sx)))
    h = max(1, int(round(int(box["h"]) * sy)))
    x = max(0, min(x, max(dst_w - 1, 0)))
    y = max(0, min(y, max(dst_h - 1, 0)))
    w = min(w, max(dst_w - x, 1))
    h = min(h, max(dst_h - y, 1))
    return {"x": x, "y": y, "w": w, "h": h}


def _norm_box(box: dict, width: int, height: int) -> tuple[float, float, float, float]:
    return (
        int(box["x"]) / max(width, 1),
        int(box["y"]) / max(height, 1),
        int(box["w"]) / max(width, 1),
        int(box["h"]) / max(height, 1),
    )


def boxes_close(left: dict, right: dict, width: int, height: int) -> bool:
    a = _norm_box(left, width, height)
    b = _norm_box(right, width, height)
    return (
        abs(a[0] - b[0]) < 0.04
        and abs(a[1] - b[1]) < 0.04
        and abs(a[2] - b[2]) < 0.05
        and abs(a[3] - b[3]) < 0.05
    )


def _score_number(text: str) -> int:
    digits = "".join(char for char in (text or "") if char.isdigit())
    if not digits:
        return 0
    length = len(digits)
    if 3 <= length <= 6:
        return length + 10
    return length


def _clean_box(box: dict) -> dict[str, int]:
    return {
        "x": int(box["x"]),
        "y": int(box["y"]),
        "w": max(1, int(box["w"])),
        "h": max(1, int(box["h"])),
    }


def _box_patterns_path() -> Path:
    return trainer_data_dir() / "coin_box_patterns.json"


class CoinReader:
    def __init__(self) -> None:
        self._hud = _load("_tsum_hud_number", "hud_number.py")
        self._digit_mod = _load("_tsum_digit_model", "digit_model.py")
        self._region_mod = _load("_tsum_region_model", "model.py")
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._region_models: dict[str, object] = {}
        self._digit_models: dict[str, object] = {}
        self._patterns: dict[str, list[tuple[dict[str, int], int, int]]] = {"coin": [], "result_coin": []}
        self._fallback: dict[str, tuple[dict[str, int], int, int]] = {}
        self._region_transform = transforms.Compose(
            [
                transforms.Resize((INPUT_SIZE, INPUT_SIZE)),
                transforms.ToTensor(),
                transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
            ]
        )
        self._digit_transform = transforms.Compose(
            [
                transforms.Resize((self._digit_mod.DIGIT_HEIGHT, self._digit_mod.DIGIT_WIDTH)),
                transforms.ToTensor(),
                transforms.Normalize(self._digit_mod.IMAGENET_MEAN, self._digit_mod.IMAGENET_STD),
            ]
        )
        self._load_models()
        self._load_fallbacks()

    def _models_dir(self) -> Path:
        return trainer_data_dir() / "models"

    def _load_models(self) -> None:
        models_dir = self._models_dir()
        for key in ("coin", "result_coin"):
            path = models_dir / f"{key}.pt" if key != "coin" else models_dir / "coin.pt"
            if not path.is_file():
                continue
            checkpoint = torch.load(path, map_location=self.device, weights_only=False)
            model = self._region_mod.GameRegionNet(pretrained=False)
            state = (
                checkpoint["state_dict"]
                if isinstance(checkpoint, dict) and "state_dict" in checkpoint
                else checkpoint
            )
            model.load_state_dict(state)
            model.to(self.device)
            model.eval()
            self._region_models[key] = model
        self._digit_models = {}
        digit_files = (("coin", "coin_digits.pt"), ("result_coin", "result_coin_digits.pt"))
        for key, filename in digit_files:
            path = models_dir / filename
            if not path.is_file():
                continue
            checkpoint = torch.load(path, map_location=self.device, weights_only=False)
            model = self._digit_mod.CoinDigitNet(pretrained=False)
            state = (
                checkpoint["state_dict"]
                if isinstance(checkpoint, dict) and "state_dict" in checkpoint
                else checkpoint
            )
            try:
                model.load_state_dict(state)
            except Exception:
                continue
            model.to(self.device)
            model.eval()
            self._digit_models[key] = model
        if "coin" in self._digit_models and "result_coin" not in self._digit_models:
            self._digit_models["result_coin"] = self._digit_models["coin"]

    def _load_fallbacks(self) -> None:
        self._patterns = {"coin": [], "result_coin": []}
        self._fallback = {}
        index_path = trainer_data_dir() / "index.json"
        if index_path.is_file():
            try:
                payload = json.loads(index_path.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
            for sample in reversed(payload.get("samples") or []):
                width = int(sample.get("width") or 0)
                height = int(sample.get("height") or 0)
                regions = sample.get("regions") or {}
                for key in ("coin", "result_coin"):
                    box = regions.get(key)
                    if not box or width <= 0 or height <= 0:
                        continue
                    cleaned = _clean_box(box)
                    self._remember_pattern(key, cleaned, width, height)
                    if key not in self._fallback:
                        self._fallback[key] = (cleaned, width, height)
        self._load_saved_box_patterns()

    def _load_saved_box_patterns(self) -> None:
        path = _box_patterns_path()
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        for key in ("coin", "result_coin"):
            for item in payload.get(key) or []:
                box = item.get("box") if isinstance(item, dict) else None
                width = int(item.get("width") or 0) if isinstance(item, dict) else 0
                height = int(item.get("height") or 0) if isinstance(item, dict) else 0
                if not box or width <= 0 or height <= 0:
                    continue
                cleaned = _clean_box(box)
                self._remember_pattern(key, cleaned, width, height)
                if key not in self._fallback:
                    self._fallback[key] = (cleaned, width, height)

    def _save_box_patterns(self) -> None:
        payload = {"coin": [], "result_coin": []}
        for key in ("coin", "result_coin"):
            for box, width, height in self._patterns.get(key) or []:
                payload[key].append(
                    {"box": _clean_box(box), "width": int(width), "height": int(height)}
                )
        path = _box_patterns_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _remember_pattern(self, key: str, box: dict[str, int], width: int, height: int) -> bool:
        rows = self._patterns.setdefault(key, [])
        for existing, src_w, src_h in rows:
            scaled = _scale_box(existing, src_w, src_h, width, height)
            if boxes_close(scaled, box, width, height):
                return False
        rows.append((_clean_box(box), width, height))
        return True

    def add_session_pattern(
        self, key: str, box: dict[str, int], width: int, height: int, persist: bool = False
    ) -> None:
        if key not in {"coin", "result_coin"} or width <= 0 or height <= 0:
            return
        added = self._remember_pattern(key, _clean_box(box), width, height)
        if persist:
            try:
                self._save_box_patterns()
            except Exception:
                pass

    def scaled_pattern_boxes(
        self,
        width: int,
        height: int,
        key: str,
        extra: list[tuple[dict[str, int], int, int]] | None = None,
    ) -> list[dict[str, int]]:
        boxes: list[dict[str, int]] = []
        rows = list(self._patterns.get(key) or [])
        if extra:
            rows = list(extra) + rows
        for box, src_w, src_h in rows:
            scaled = _scale_box(box, src_w, src_h, width, height)
            if any(boxes_close(scaled, seen, width, height) for seen in boxes):
                continue
            boxes.append(scaled)
        return boxes

    def _decode_box(self, model, image: Image.Image) -> dict[str, int]:
        width, height = image.size
        tensor = self._region_transform(image.convert("RGB")).unsqueeze(0).to(self.device)
        with torch.no_grad():
            x, y, w, h = model(tensor)[0].tolist()
        px = int(round(x * width))
        py = int(round(y * height))
        pw = int(round(w * width))
        ph = int(round(h * height))
        px = max(0, min(px, width - 1))
        py = max(0, min(py, height - 1))
        pw = max(1, min(pw, width - px))
        ph = max(1, min(ph, height - py))
        return {"x": px, "y": py, "w": pw, "h": ph}

    def _candidate_boxes(
        self,
        image: Image.Image,
        key: str,
        extra: list[tuple[dict[str, int], int, int]] | None = None,
    ) -> list[dict[str, int]]:
        boxes = self.scaled_pattern_boxes(image.width, image.height, key, extra)
        model = self._region_models.get(key)
        if model is not None:
            predicted = self._decode_box(model, image)
            if not any(boxes_close(predicted, seen, image.width, image.height) for seen in boxes):
                boxes.append(predicted)
        if boxes:
            return boxes
        fallback = self._fallback.get(key)
        if fallback is None:
            return []
        box, src_w, src_h = fallback
        return [_scale_box(box, src_w, src_h, image.width, image.height)]

    def box_for(
        self,
        image: Image.Image,
        key: str,
        extra: list[tuple[dict[str, int], int, int]] | None = None,
    ) -> dict[str, int] | None:
        boxes = self._candidate_boxes(image, key, extra)
        return boxes[0] if boxes else None

    def candidate_boxes_for_path(
        self,
        path: Path,
        key: str,
        extra: list[tuple[dict[str, int], int, int]] | None = None,
    ) -> list[dict[str, int]]:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        return self._candidate_boxes(image, key, extra)

    def _predict_digits(self, crop: Image.Image, key: str = "coin") -> str:
        model = self._digit_models.get(key) or self._digit_models.get("coin")
        if model is None and self._digit_models:
            model = next(iter(self._digit_models.values()))
        if model is None:
            return ""
        tensor = self._digit_transform(crop.convert("RGB")).unsqueeze(0).to(self.device)
        with torch.no_grad():
            logits = model(tensor)
        return self._digit_mod.decode_logits(logits.cpu())

    def _read_with_box(self, path: Path, box: dict[str, int], key: str = "coin") -> str:
        predict = None
        if self._digit_models:
            predict = lambda crop, box_key=key: self._predict_digits(crop, box_key)
        _crop, number = self._hud.read_coin_number(
            path,
            box,
            predict_fn=predict,
        )
        return number or ""

    def inspect_path(
        self,
        path: Path,
        key: str,
        extra: list[tuple[dict[str, int], int, int]] | None = None,
    ) -> tuple[dict[str, int] | None, str]:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        boxes = self._candidate_boxes(image, key, extra)
        if not boxes:
            return None, ""
        best_box = boxes[0]
        best_number = ""
        best_score = -1
        for box in boxes:
            number = self._read_with_box(path, box, key)
            score = _score_number(number)
            if score > best_score:
                best_score = score
                best_box = box
                best_number = number
        return best_box, best_number

    def read_box(self, path: Path, box: dict[str, int], key: str = "coin") -> str:
        return self._read_with_box(path, box, key)

    def read_path(self, path: Path, key: str) -> str:
        _box, number = self.inspect_path(path, key)
        return number

    def reload(self) -> None:
        self.close()
        self._load_models()
        self._load_fallbacks()

    def read_image(self, image: Image.Image, key: str) -> str:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            temp = Path(handle.name)
        try:
            image.convert("RGB").save(temp, format="PNG")
            return self.read_path(temp, key)
        finally:
            temp.unlink(missing_ok=True)

    def close(self) -> None:
        self._region_models = {}
        self._digit_models = {}
        if self.device.type == "cuda":
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
