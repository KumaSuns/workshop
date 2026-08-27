from __future__ import annotations

from pathlib import Path

import torch
from PIL import Image
from torchvision import transforms

from app.digit_model import (
    DIGIT_HEIGHT,
    DIGIT_WIDTH,
    IMAGENET_MEAN as DIGIT_MEAN,
    IMAGENET_STD as DIGIT_STD,
    CoinDigitNet,
    decode_logits,
)
from app.hud_number import prepare_digit_crop
from app.model import INPUT_SIZE, IMAGENET_MEAN, IMAGENET_STD, GameRegionNet
from app.piece_model import HEATMAP_SIZE, PIECE_INPUT, PieceNet, peaks_from_heat
from app.regions import PIECE_KEYS, REGION_KEYS, SCENE_KEYS, model_filename, piece_radius_from_game
from app.scene_model import SCENE_INPUT, SceneNet, scene_name


class Predictor:
    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.models: dict[str, GameRegionNet] = {}
        self.piece_model: PieceNet | None = None
        self.digit_models: dict[str, CoinDigitNet] = {}
        self.scene_model: SceneNet | None = None
        self._transform = transforms.Compose(
            [
                transforms.Resize((INPUT_SIZE, INPUT_SIZE)),
                transforms.ToTensor(),
                transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
            ]
        )
        self._piece_transform = transforms.Compose(
            [
                transforms.Resize((PIECE_INPUT, PIECE_INPUT)),
                transforms.ToTensor(),
                transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
            ]
        )
        self._digit_transform = transforms.Compose(
            [
                transforms.Resize((DIGIT_HEIGHT, DIGIT_WIDTH)),
                transforms.ToTensor(),
                transforms.Normalize(DIGIT_MEAN, DIGIT_STD),
            ]
        )
        self._scene_transform = transforms.Compose(
            [
                transforms.Resize((SCENE_INPUT, SCENE_INPUT)),
                transforms.ToTensor(),
                transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
            ]
        )
        self.reload()

    def release(self) -> None:
        self.models = {}
        self.piece_model = None
        self.digit_models = {}
        self.scene_model = None
        if self.device.type == "cuda":
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass

    def is_ready(self) -> bool:
        return (
            bool(self.models)
            or self.piece_model is not None
            or bool(self.digit_models)
            or self.scene_model is not None
        )

    def ready_keys(self) -> list[str]:
        keys = [key for key in REGION_KEYS if key in self.models]
        if self.piece_model is not None:
            keys.extend(PIECE_KEYS)
        if self.digit_models:
            keys.append("coin_digits")
        if self.scene_model is not None:
            keys.extend(SCENE_KEYS)
        return keys

    def reload(self) -> bool:
        self.models = {}
        self.piece_model = None
        self.digit_models = {}
        self.scene_model = None
        for key in REGION_KEYS:
            path = self.models_dir / model_filename(key)
            if not path.exists():
                continue
            checkpoint = torch.load(path, map_location=self.device, weights_only=False)
            model = GameRegionNet(pretrained=False)
            state = (
                checkpoint["state_dict"]
                if isinstance(checkpoint, dict) and "state_dict" in checkpoint
                else checkpoint
            )
            model.load_state_dict(state)
            model.to(self.device)
            model.eval()
            self.models[key] = model
        piece_path = self.models_dir / model_filename("pieces")
        if piece_path.exists():
            checkpoint = torch.load(piece_path, map_location=self.device, weights_only=False)
            model = PieceNet(pretrained=False)
            state = (
                checkpoint["state_dict"]
                if isinstance(checkpoint, dict) and "state_dict" in checkpoint
                else checkpoint
            )
            model.load_state_dict(state)
            model.to(self.device)
            model.eval()
            self.piece_model = model
        self.digit_models = {}
        for key, filename in (("coin", "coin_digits.pt"), ("result_coin", "result_coin_digits.pt")):
            path = self.models_dir / filename
            if not path.exists():
                continue
            checkpoint = torch.load(path, map_location=self.device, weights_only=False)
            model = CoinDigitNet(pretrained=False)
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
            self.digit_models[key] = model
        if "coin" in self.digit_models and "result_coin" not in self.digit_models:
            self.digit_models["result_coin"] = self.digit_models["coin"]
        scene_path = self.models_dir / model_filename("scene")
        if scene_path.exists():
            checkpoint = torch.load(scene_path, map_location=self.device, weights_only=False)
            model = SceneNet(pretrained=False)
            state = (
                checkpoint["state_dict"]
                if isinstance(checkpoint, dict) and "state_dict" in checkpoint
                else checkpoint
            )
            model.load_state_dict(state)
            model.to(self.device)
            model.eval()
            self.scene_model = model
        return self.is_ready()

    def predict_scene(self, image_path: Path) -> tuple[str, float]:
        if self.scene_model is None:
            return "other", 0.0
        with Image.open(image_path) as image:
            tensor = self._scene_transform(image.convert("RGB")).unsqueeze(0).to(self.device)
        with torch.no_grad():
            logits = self.scene_model(tensor)
            probs = torch.softmax(logits, dim=1)[0]
        index = int(probs.argmax().item())
        return scene_name(index), float(probs[index].item())

    @property
    def digit_model(self) -> CoinDigitNet | None:
        return self.digit_models.get("coin") or next(iter(self.digit_models.values()), None)

    def predict_coin_digits(self, crop: Image.Image, key: str = "coin") -> str:
        model = self.digit_models.get(key) or self.digit_model
        if model is None:
            return ""
        crop = prepare_digit_crop(crop, key)
        tensor = self._digit_transform(crop.convert("RGB")).unsqueeze(0).to(self.device)
        with torch.no_grad():
            logits = model(tensor)
        return decode_logits(logits.cpu())

    def predict_all(self, image_path: Path) -> dict[str, dict[str, int]]:
        if not self.models:
            return {}
        with Image.open(image_path) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            tensor = self._transform(rgb).unsqueeze(0).to(self.device)
        boxes: dict[str, dict[str, int]] = {}
        for key, model in self.models.items():
            boxes[key] = self._decode(model, tensor, width, height)
        return boxes

    def predict_pieces(self, image_path: Path, game: dict[str, int] | None) -> list[dict[str, int]]:
        if self.piece_model is None:
            return []
        with Image.open(image_path) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            if game is None:
                left, top, crop_w, crop_h = 0, 0, width, height
            else:
                left = max(0, int(game["x"]))
                top = max(0, int(game["y"]))
                crop_w = max(1, int(game["w"]))
                crop_h = max(1, int(game["h"]))
            right = min(width, left + crop_w)
            bottom = min(height, top + crop_h)
            crop = rgb.crop((left, top, right, bottom))
            crop_w = max(1, right - left)
            crop_h = max(1, bottom - top)
            tensor = self._piece_transform(crop).unsqueeze(0).to(self.device)
        with torch.no_grad():
            heat, radius = self.piece_model(tensor)
        heat = heat[0].cpu()
        radius = radius[0, 0].cpu()
        pieces: list[dict[str, int]] = []
        board_w = int(game["w"]) if game is not None else crop_w
        for channel, kind in enumerate(("tsum", "bomb")):
            for _score, hx, hy, _r_norm in peaks_from_heat(heat[channel], radius):
                x = int(round(left + hx / HEATMAP_SIZE * crop_w))
                y = int(round(top + hy / HEATMAP_SIZE * crop_h))
                r = piece_radius_from_game(board_w, kind)
                pieces.append({"x": x, "y": y, "r": r, "kind": kind, "group": 1})
        self._assign_groups(rgb, pieces)
        return pieces

    def _assign_groups(self, image: Image.Image, pieces: list[dict[str, int]]) -> None:
        refs: list[tuple[float, float, float]] = []
        for piece in pieces:
            if piece["kind"] != "tsum":
                piece["group"] = 0
                continue
            color = self._mean_color(image, piece)
            group = None
            for index, ref in enumerate(refs, start=1):
                dist = (
                    (color[0] - ref[0]) ** 2
                    + (color[1] - ref[1]) ** 2
                    + (color[2] - ref[2]) ** 2
                ) ** 0.5
                if dist < 48:
                    group = min(index, 12)
                    break
            if group is None:
                refs.append(color)
                group = min(len(refs), 12)
            piece["group"] = group

    def _mean_color(self, image: Image.Image, piece: dict[str, int]) -> tuple[float, float, float]:
        x, y, r = int(piece["x"]), int(piece["y"]), max(4, int(piece["r"]))
        box = (max(0, x - r), max(0, y - r), x + r, y + r)
        crop = image.crop(box)
        pixels = list(crop.getdata())
        if not pixels:
            return (0.0, 0.0, 0.0)
        count = len(pixels)
        return (
            sum(p[0] for p in pixels) / count,
            sum(p[1] for p in pixels) / count,
            sum(p[2] for p in pixels) / count,
        )

    def _decode(
        self,
        model: GameRegionNet,
        tensor: torch.Tensor,
        width: int,
        height: int,
    ) -> dict[str, int]:
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
