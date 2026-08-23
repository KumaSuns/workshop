from __future__ import annotations

import random

import torch
from PIL import Image
from PySide6.QtCore import QThread, Signal
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.transforms import functional as TF

from app.data_sync import bundle_dir
from app.scene_labels import MIN_SCENE_SAMPLES, SceneLabels
from app.scene_scan import IMAGENET_MEAN, IMAGENET_STD, SCENE_INPUT, SceneNet


class SceneImageDataset(Dataset):
    def __init__(self, items: list[dict[str, str]], classes: tuple[str, ...], augment: bool = True) -> None:
        self.items = items
        self.classes = classes
        self.augment = augment
        self.jitter = transforms.ColorJitter(0.2, 0.2, 0.2, 0.04)
        self.normalize = transforms.Compose(
            [
                transforms.Resize((SCENE_INPUT, SCENE_INPUT)),
                transforms.ToTensor(),
                transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
            ]
        )

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        item = self.items[index]
        image = Image.open(item["path"]).convert("RGB")
        if self.augment:
            image = self.jitter(image)
            if random.random() < 0.5:
                image = TF.hflip(image)
        label = self.classes.index(item["kind"])
        return self.normalize(image), torch.tensor(label, dtype=torch.long)


class SceneTrainWorker(QThread):
    progress = Signal(int, int, str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, labels: SceneLabels, epochs: int = 40) -> None:
        super().__init__()
        self.labels = labels
        self.epochs = epochs

    def _emit(self, current: int, total: int, message: str) -> None:
        self.progress.emit(current, total, message)
        self.msleep(1)

    def run(self) -> None:
        try:
            self._emit(0, max(self.epochs, 1), "学習中です  準備しています")
            result = self._train()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        finally:
            if torch.cuda.is_available():
                try:
                    torch.cuda.empty_cache()
                except Exception:
                    pass
        self.finished_ok.emit(result)

    def _train(self) -> dict:
        missing = self.labels.missing_for_train()
        if missing:
            raise ValueError(
                f"各種類 {MIN_SCENE_SAMPLES} 枚以上必要です。\n" + "\n".join(missing)
            )
        classes = self.labels.train_classes()
        allowed = set(classes)
        items = [item for item in self.labels.items() if item["kind"] in allowed]
        counts = self.labels.counts()
        self._emit(0, max(self.epochs, 1), "学習中です  画像を読んでいます")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        dataset = SceneImageDataset(items, classes, augment=True)
        loader = DataLoader(dataset, batch_size=min(8, len(dataset)), shuffle=True, num_workers=0)
        self._emit(0, max(self.epochs, 1), "学習中です  モデルを用意しています")
        model = SceneNet(pretrained=True, num_classes=len(classes))
        model.freeze_backbone(train_last_block=True)
        model.to(device)
        trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
        optimizer = torch.optim.AdamW(trainable, lr=1e-3, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=self.epochs)
        weights = torch.tensor(
            [1.0 / max(counts.get(key, 0), 1) for key in classes],
            dtype=torch.float32,
            device=device,
        )
        weights = weights / weights.sum() * len(classes)
        loss_fn = torch.nn.CrossEntropyLoss(weight=weights)
        best_acc = -1.0
        best_state = None
        model_path = bundle_dir() / "scene.pt"
        model_path.parent.mkdir(parents=True, exist_ok=True)
        batches = max(len(loader), 1)
        self._emit(0, self.epochs * batches, "学習中です  準備しています")
        for epoch in range(1, self.epochs + 1):
            if self.isInterruptionRequested():
                raise RuntimeError("学習を中止しました")
            model.train()
            total_loss = 0.0
            total_correct = 0
            seen = 0
            for batch_index, (images, targets) in enumerate(loader, start=1):
                if self.isInterruptionRequested():
                    raise RuntimeError("学習を中止しました")
                images = images.to(device)
                targets = targets.to(device)
                optimizer.zero_grad(set_to_none=True)
                logits = model(images)
                loss = loss_fn(logits, targets)
                loss.backward()
                optimizer.step()
                batch = images.size(0)
                total_loss += loss.item() * batch
                total_correct += int((logits.argmax(dim=-1) == targets).sum().item())
                seen += batch
                step = (epoch - 1) * batches + batch_index
                self._emit(
                    step,
                    self.epochs * batches,
                    f"学習中です  {epoch}/{self.epochs}  （{batch_index}/{batches}）",
                )
            scheduler.step()
            acc = total_correct / max(seen, 1)
            if acc > best_acc:
                best_acc = acc
                best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            self._emit(
                epoch * batches,
                self.epochs * batches,
                f"学習中です  {epoch}/{self.epochs}  精度 {acc:.0%}",
            )
        if best_state is None:
            raise RuntimeError("学習結果を保存できませんでした")
        torch.save(
            {
                "state_dict": best_state,
                "acc": best_acc,
                "key": "scene",
                "samples": len(items),
                "classes": list(classes),
            },
            model_path,
        )
        return {"acc": float(best_acc), "samples": len(items)}
