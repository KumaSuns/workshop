from __future__ import annotations

import random
from pathlib import Path

import torch
from PIL import Image
from PySide6.QtCore import QThread, Signal
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.transforms import functional as TF

from app.dataset import Sample
from app.model import INPUT_SIZE, IMAGENET_MEAN, IMAGENET_STD, GameRegionNet

MIN_TRAIN_SAMPLES = 5


class RegionBoxDataset(Dataset):
    def __init__(self, samples: list[Sample], augment: bool = True) -> None:
        self.samples = samples
        self.augment = augment
        self.jitter = transforms.ColorJitter(0.25, 0.25, 0.25, 0.05)
        self.normalize = transforms.Compose(
            [
                transforms.Resize((INPUT_SIZE, INPUT_SIZE)),
                transforms.ToTensor(),
                transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
            ]
        )

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        sample = self.samples[index]
        region = sample.game_region or {"x": 0, "y": 0, "w": sample.width, "h": sample.height}
        image = Image.open(sample.image_path).convert("RGB")
        x = region["x"] / sample.width
        y = region["y"] / sample.height
        w = region["w"] / sample.width
        h = region["h"] / sample.height
        if self.augment:
            image = self.jitter(image)
            if random.random() < 0.5:
                image = TF.hflip(image)
                x = 1.0 - x - w
        box = torch.tensor([x, y, w, h], dtype=torch.float32)
        return self.normalize(image), box


def box_iou(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    pred_x2 = pred[:, 0] + pred[:, 2]
    pred_y2 = pred[:, 1] + pred[:, 3]
    tgt_x2 = target[:, 0] + target[:, 2]
    tgt_y2 = target[:, 1] + target[:, 3]
    left = torch.max(pred[:, 0], target[:, 0])
    top = torch.max(pred[:, 1], target[:, 1])
    right = torch.min(pred_x2, tgt_x2)
    bottom = torch.min(pred_y2, tgt_y2)
    inter = (right - left).clamp(min=0) * (bottom - top).clamp(min=0)
    area_pred = pred[:, 2] * pred[:, 3]
    area_tgt = target[:, 2] * target[:, 3]
    union = area_pred + area_tgt - inter
    return inter / union.clamp(min=1e-6)


class TrainWorker(QThread):
    progress = Signal(int, int, str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, samples: list[Sample], model_path: Path, epochs: int = 40) -> None:
        super().__init__()
        self.samples = samples
        self.model_path = model_path
        self.epochs = epochs

    def run(self) -> None:
        try:
            metrics = self._train()
            self.finished_ok.emit(metrics)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def _train(self) -> dict:
        if len(self.samples) < MIN_TRAIN_SAMPLES:
            raise ValueError(f"学習にはラベル済み画像が {MIN_TRAIN_SAMPLES} 枚以上必要です")

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        dataset = RegionBoxDataset(self.samples, augment=True)
        loader = DataLoader(
            dataset,
            batch_size=min(4, len(dataset)),
            shuffle=True,
            num_workers=0,
        )
        model = GameRegionNet()
        model.freeze_backbone(train_last_block=True)
        model.to(device)

        trainable = [p for p in model.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(trainable, lr=1e-3, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=self.epochs)
        loss_fn = torch.nn.SmoothL1Loss()

        best_iou = -1.0
        best_state = None
        self.model_path.parent.mkdir(parents=True, exist_ok=True)

        for epoch in range(1, self.epochs + 1):
            model.train()
            total_loss = 0.0
            total_iou = 0.0
            seen = 0
            for images, boxes in loader:
                images = images.to(device)
                boxes = boxes.to(device)
                optimizer.zero_grad(set_to_none=True)
                preds = model(images)
                loss = loss_fn(preds, boxes)
                loss.backward()
                optimizer.step()
                batch = images.size(0)
                total_loss += loss.item() * batch
                total_iou += box_iou(preds.detach(), boxes).sum().item()
                seen += batch
            scheduler.step()
            mean_loss = total_loss / max(seen, 1)
            mean_iou = total_iou / max(seen, 1)
            if mean_iou > best_iou:
                best_iou = mean_iou
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            self.progress.emit(
                epoch,
                self.epochs,
                f"epoch {epoch}/{self.epochs}  loss {mean_loss:.4f}  IoU {mean_iou:.3f}",
            )

        if best_state is None:
            raise RuntimeError("学習結果を保存できませんでした")
        torch.save({"state_dict": best_state, "iou": best_iou}, self.model_path)
        return {"iou": float(best_iou), "epochs": self.epochs, "samples": len(self.samples)}
