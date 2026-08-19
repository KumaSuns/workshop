from __future__ import annotations

from pathlib import Path

import torch
from PIL import Image
from torchvision import transforms

from app.model import INPUT_SIZE, IMAGENET_MEAN, IMAGENET_STD, GameRegionNet


class Predictor:
    def __init__(self, model_path: Path) -> None:
        self.model_path = model_path
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model: GameRegionNet | None = None
        self._transform = transforms.Compose(
            [
                transforms.Resize((INPUT_SIZE, INPUT_SIZE)),
                transforms.ToTensor(),
                transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
            ]
        )
        self.reload()

    def is_ready(self) -> bool:
        return self.model is not None

    def reload(self) -> bool:
        if not self.model_path.exists():
            self.model = None
            return False
        checkpoint = torch.load(self.model_path, map_location=self.device, weights_only=False)
        model = GameRegionNet(pretrained=False)
        state = checkpoint["state_dict"] if isinstance(checkpoint, dict) and "state_dict" in checkpoint else checkpoint
        model.load_state_dict(state)
        model.to(self.device)
        model.eval()
        self.model = model
        return True

    def predict_path(self, image_path: Path) -> dict[str, int]:
        with Image.open(image_path) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            tensor = self._transform(rgb).unsqueeze(0).to(self.device)
        return self._predict_tensor(tensor, width, height)

    def _predict_tensor(self, tensor: torch.Tensor, width: int, height: int) -> dict[str, int]:
        if self.model is None:
            raise RuntimeError("学習済みモデルがありません")
        with torch.no_grad():
            x, y, w, h = self.model(tensor)[0].tolist()
        px = int(round(x * width))
        py = int(round(y * height))
        pw = int(round(w * width))
        ph = int(round(h * height))
        px = max(0, min(px, width - 1))
        py = max(0, min(py, height - 1))
        pw = max(1, min(pw, width - px))
        ph = max(1, min(ph, height - py))
        return {"x": px, "y": py, "w": pw, "h": ph}
