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


class CoinReader:
    def __init__(self) -> None:
        self._hud = _load("_tsum_hud_number", "hud_number.py")
        self._digit_mod = _load("_tsum_digit_model", "digit_model.py")
        self._region_mod = _load("_tsum_region_model", "model.py")
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._region_models: dict[str, object] = {}
        self._digit_model = None
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
        digit_path = models_dir / "coin_digits.pt"
        if digit_path.is_file():
            checkpoint = torch.load(digit_path, map_location=self.device, weights_only=False)
            model = self._digit_mod.CoinDigitNet(pretrained=False)
            state = (
                checkpoint["state_dict"]
                if isinstance(checkpoint, dict) and "state_dict" in checkpoint
                else checkpoint
            )
            model.load_state_dict(state)
            model.to(self.device)
            model.eval()
            self._digit_model = model

    def _load_fallbacks(self) -> None:
        index_path = trainer_data_dir() / "index.json"
        if not index_path.is_file():
            return
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            return
        for sample in reversed(payload.get("samples") or []):
            width = int(sample.get("width") or 0)
            height = int(sample.get("height") or 0)
            regions = sample.get("regions") or {}
            for key in ("coin", "result_coin"):
                if key in self._fallback:
                    continue
                box = regions.get(key)
                if box and width > 0 and height > 0:
                    self._fallback[key] = (
                        {
                            "x": int(box["x"]),
                            "y": int(box["y"]),
                            "w": int(box["w"]),
                            "h": int(box["h"]),
                        },
                        width,
                        height,
                    )

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

    def box_for(self, image: Image.Image, key: str) -> dict[str, int] | None:
        model = self._region_models.get(key)
        if model is not None:
            return self._decode_box(model, image)
        fallback = self._fallback.get(key)
        if fallback is None:
            return None
        box, src_w, src_h = fallback
        return _scale_box(box, src_w, src_h, image.width, image.height)

    def _predict_digits(self, crop: Image.Image) -> str:
        if self._digit_model is None:
            return ""
        tensor = self._digit_transform(crop.convert("RGB")).unsqueeze(0).to(self.device)
        with torch.no_grad():
            logits = self._digit_model(tensor)
        return self._digit_mod.decode_logits(logits.cpu())

    def read_path(self, path: Path, key: str) -> str:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        box = self.box_for(image, key)
        if box is None:
            return ""
        _crop, number = self._hud.read_coin_number(
            path,
            box,
            predict_fn=self._predict_digits if self._digit_model is not None else None,
        )
        return number or ""

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
        self._digit_model = None
        if self.device.type == "cuda":
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
