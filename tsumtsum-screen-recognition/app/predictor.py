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
from app.piece_model import HEATMAP_SIZE, PIECE_INPUT, PieceNet, heat_to_pixel, peaks_from_heat
from app.paths import WORKSHOP_ROOT
from app.regions import PIECE_KEYS, REGION_KEYS, SCENE_KEYS, model_filename, piece_radius_from_game
from app.scene_model import SCENE_INPUT, SceneNet, scene_name
from app.tsum_type import (
    IMAGENET_MEAN as TYPE_MEAN,
    IMAGENET_STD as TYPE_STD,
    TYPE_INPUT,
    TsumTypeNet,
    TYPE_CROP_SCALE,
    prepare_tsum_crop,
)


class Predictor:
    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.models: dict[str, GameRegionNet] = {}
        self.piece_model: PieceNet | None = None
        self.type_model: TsumTypeNet | None = None
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
        self._type_transform = transforms.Compose(
            [
                transforms.Resize((TYPE_INPUT, TYPE_INPUT)),
                transforms.ToTensor(),
                transforms.Normalize(TYPE_MEAN, TYPE_STD),
            ]
        )
        self.reload()

    def release(self) -> None:
        self.models = {}
        self.piece_model = None
        self.type_model = None
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
        self.type_model = None
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
            model.load_state_dict(state, strict=False)
            model.to(self.device)
            model.eval()
            self.piece_model = model
        type_path = self.models_dir / model_filename("tsum_types")
        if type_path.exists():
            checkpoint = torch.load(type_path, map_location=self.device, weights_only=False)
            model = TsumTypeNet(pretrained=False)
            state = (
                checkpoint["state_dict"]
                if isinstance(checkpoint, dict) and "state_dict" in checkpoint
                else checkpoint
            )
            try:
                model.load_state_dict(state)
            except Exception:
                model = None
            if model is not None:
                model.to(self.device)
                model.eval()
                self.type_model = model
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
        if not scene_path.exists():
            scene_path = WORKSHOP_ROOT / "video-frame-extractor" / "scene.pt"
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

    def predict_all(self, image_path: Path, rgb: Image.Image | None = None) -> dict[str, dict[str, int]]:
        if not self.models:
            return {}
        if rgb is None:
            with Image.open(image_path) as image:
                rgb = image.convert("RGB")
        else:
            rgb = rgb.convert("RGB")
        width, height = rgb.size
        tensor = self._transform(rgb).unsqueeze(0).to(self.device)
        boxes: dict[str, dict[str, int]] = {}
        for key, model in self.models.items():
            boxes[key] = self._decode(model, tensor, width, height)
        return boxes

    def predict_pieces(
        self,
        image_path: Path,
        game: dict[str, int] | None,
        kinds: int = 5,
        rgb: Image.Image | None = None,
    ) -> list[dict[str, int]]:
        if self.piece_model is None:
            return []
        if rgb is None:
            with Image.open(image_path) as image:
                rgb = image.convert("RGB")
        else:
            rgb = rgb.convert("RGB")
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
                x, y = heat_to_pixel(hx, hy, left, top, crop_w, crop_h)
                r = piece_radius_from_game(board_w, kind)
                pieces.append(
                    {"x": int(round(x)), "y": int(round(y)), "r": r, "kind": kind, "group": 1}
                )
        self._assign_groups(rgb, pieces, kinds=kinds)
        return pieces

    def _assign_groups(
        self,
        image: Image.Image,
        pieces: list[dict[str, int]],
        kinds: int = 5,
    ) -> None:
        tsums: list[dict[str, int]] = []
        for piece in pieces:
            if piece["kind"] != "tsum":
                piece["group"] = 0
            else:
                tsums.append(piece)
        if not tsums:
            return
        colors = [self._tsum_color(image, piece) for piece in tsums]
        k = min(max(1, kinds), len(tsums))
        labels = self._kmeans(colors, k, cosine=False)
        if self.type_model is not None:
            embeds = self._tsum_embeddings(image, tsums)
            for _ in range(2):
                labels = self._split_mixed_clusters(embeds, labels, cosine=True)
        uniq = sorted(set(labels))
        order = sorted(
            uniq,
            key=lambda g: (
                -sum(1 for label in labels if label == g),
                next((colors[i][0] for i, label in enumerate(labels) if label == g), 0.0),
            ),
        )
        remap = {old: new for new, old in enumerate(order, start=1)}
        for piece, label in zip(tsums, labels):
            piece["group"] = remap[label]

    def _split_mixed_clusters(
        self,
        points: list[tuple[float, ...]],
        labels: list[int],
        cosine: bool,
        min_size: int = 3,
        max_center_sim: float = 0.82,
    ) -> list[int]:
        next_label = max(labels, default=0) + 1
        updated = list(labels)
        for group in sorted(set(labels)):
            members = [index for index, label in enumerate(labels) if label == group]
            if len(members) < min_size * 2:
                continue
            subpoints = [points[index] for index in members]
            sub = self._kmeans(subpoints, 2, cosine=cosine)
            left = [members[index] for index, label in enumerate(sub) if label == 0]
            right = [members[index] for index, label in enumerate(sub) if label == 1]
            if len(left) < min_size or len(right) < min_size:
                continue
            if not cosine:
                continue
            center_left = self._mean_point([points[index] for index in left], cosine)
            center_right = self._mean_point([points[index] for index in right], cosine)
            sim = sum(a * b for a, b in zip(center_left, center_right))
            if sim >= max_center_sim:
                continue
            for index in right:
                updated[index] = next_label
            next_label += 1
        return updated

    def _mean_point(self, points: list[tuple[float, ...]], cosine: bool) -> list[float]:
        dim = len(points[0])
        center = [sum(point[d] for point in points) / len(points) for d in range(dim)]
        if cosine:
            scale = (sum(value * value for value in center) ** 0.5) or 1.0
            center = [value / scale for value in center]
        return center

    def _tsum_embeddings(
        self, image: Image.Image, pieces: list[dict[str, int]]
    ) -> list[tuple[float, ...]]:
        tensors = [self._type_transform(prepare_tsum_crop(image, piece)) for piece in pieces]
        batch = torch.stack(tensors).to(self.device)
        model = self.type_model
        if model is None:
            return [self._tsum_color(image, piece) for piece in pieces]
        with torch.no_grad():
            encoded = model(batch).cpu()
        return [tuple(row.tolist()) for row in encoded]

    def _tsum_color(self, image: Image.Image, piece: dict[str, int]) -> tuple[float, float, float]:
        x, y, r = int(piece["x"]), int(piece["y"]), max(4, int(piece["r"]))
        span = max(8, int(round(r * TYPE_CROP_SCALE)))
        width, height = image.size
        box = (
            max(0, x - span),
            max(0, y - span),
            min(width, x + span + 1),
            min(height, y + span + 1),
        )
        crop = image.crop(box).resize((32, 32), Image.Resampling.BILINEAR).convert("LAB")
        cx = cy = 15.5
        ring: list[tuple[int, int, int]] = []
        for index, pixel in enumerate(crop.getdata()):
            px = index % 32
            py = index // 32
            dist = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
            if dist < 4.0 or dist > 9.0:
                continue
            ring.append((int(pixel[0]), int(pixel[1]), int(pixel[2])))
        if not ring:
            return (0.0, 128.0, 128.0)
        luma = sorted(pixel[0] for pixel in ring)
        median_l = luma[len(luma) // 2]
        kept = [pixel for pixel in ring if pixel[0] <= median_l + 28]
        if not kept:
            kept = ring
        count = len(kept)
        total = [sum(pixel[i] for pixel in kept) / count for i in range(3)]
        return (0.3 * total[0], total[1], total[2])

    def _kmeans(self, points: list[tuple[float, ...]], k: int, iters: int = 16, cosine: bool = False) -> list[int]:
        if k <= 1 or len(points) <= 1:
            return [0] * len(points)
        best_labels: list[int] | None = None
        best_inertia = 0.0
        for start in range(min(8, len(points))):
            labels, inertia = self._kmeans_once(points, k, iters, start, cosine)
            if best_labels is None or inertia < best_inertia:
                best_labels = labels
                best_inertia = inertia
        return best_labels or [0] * len(points)

    def _kmeans_once(
        self,
        points: list[tuple[float, ...]],
        k: int,
        iters: int,
        start: int,
        cosine: bool,
    ) -> tuple[list[int], float]:
        dist = self._cosine_dist2 if cosine else self._euclid_dist2
        centers: list[list[float]] = [list(points[start])]
        for _ in range(k - 1):
            best_index = 0
            best_dist = -1.0
            for index, point in enumerate(points):
                d = min(dist(point, center) for center in centers)
                if d > best_dist:
                    best_dist = d
                    best_index = index
            centers.append(list(points[best_index]))
        labels = [0] * len(points)
        dim = len(points[0])
        for _ in range(iters):
            for index, point in enumerate(points):
                labels[index] = min(range(k), key=lambda g: dist(point, centers[g]))
            for group in range(k):
                members = [points[i] for i, label in enumerate(labels) if label == group]
                if not members:
                    continue
                centers[group] = [sum(member[d] for member in members) / len(members) for d in range(dim)]
                if cosine:
                    scale = (sum(c * c for c in centers[group]) ** 0.5) or 1.0
                    centers[group] = [c / scale for c in centers[group]]
        inertia = sum(dist(point, centers[label]) for point, label in zip(points, labels))
        return labels, inertia

    def _euclid_dist2(self, a: tuple[float, ...] | list[float], b: tuple[float, ...] | list[float]) -> float:
        return sum((float(x) - float(y)) ** 2 for x, y in zip(a, b))

    def _cosine_dist2(self, a: tuple[float, ...] | list[float], b: tuple[float, ...] | list[float]) -> float:
        return 2.0 - 2.0 * sum(float(x) * float(y) for x, y in zip(a, b))

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
