from __future__ import annotations

from pathlib import Path

import torch
from PIL import Image
from torchvision import transforms

from app.model import INPUT_SIZE, IMAGENET_MEAN, IMAGENET_STD, GameRegionNet
from app.regions import REGION_KEYS, model_filename


class Predictor:
    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.models: dict[str, GameRegionNet] = {}
        self._transform = transforms.Compose(
            [
                transforms.Resize((INPUT_SIZE, INPUT_SIZE)),
                transforms.ToTensor(),
                transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
            ]
        )
        self.reload()

    def is_ready(self) -> bool:
        return bool(self.models)

    def ready_keys(self) -> list[str]:
        return [key for key in REGION_KEYS if key in self.models]

    def reload(self) -> bool:
        self.models = {}
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
        return bool(self.models)

    def predict_all(self, image_path: Path) -> dict[str, dict[str, int]]:
        if not self.models:
            raise RuntimeError("学習済みモデルがありません")
        with Image.open(image_path) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            tensor = self._transform(rgb).unsqueeze(0).to(self.device)
        boxes: dict[str, dict[str, int]] = {}
        for key, model in self.models.items():
            boxes[key] = self._decode(model, tensor, width, height)
        return boxes

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
