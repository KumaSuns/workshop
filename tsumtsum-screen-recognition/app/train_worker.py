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
from app.digit_model import (
    DIGIT_HEIGHT,
    DIGIT_WIDTH,
    IMAGENET_MEAN as DIGIT_MEAN,
    IMAGENET_STD as DIGIT_STD,
    CoinDigitNet,
    decode_indices,
    decode_logits,
    digit_layout_for_key,
    encode_digits,
)
from app.hud_number import crop_box, prepare_digit_crop
from app.model import INPUT_SIZE, IMAGENET_MEAN, IMAGENET_STD, GameRegionNet
from app.piece_model import HEATMAP_SIZE, KIND_CHANNELS, PIECE_INPUT, PieceNet, draw_gaussian
from app.regions import REGION_LABELS
from app.scene_model import SCENE_INPUT, SceneNet, scene_index

MIN_TRAIN_SAMPLES = 5
TRAIN_EPOCHS = 40


def _checkpoint(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        payload = torch.load(path, map_location="cpu", weights_only=False)
    except Exception:
        return {}
    if isinstance(payload, dict):
        return payload
    return {"state_dict": payload}


class TrainingCancelled(Exception):
    pass


class RegionBoxDataset(Dataset):
    def __init__(self, samples: list[Sample], key: str, augment: bool = True) -> None:
        self.samples = samples
        self.key = key
        self.augment = augment
        self.allow_flip = key == "game"
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
        region = sample.regions[self.key]
        image = Image.open(sample.image_path).convert("RGB")
        x = region["x"] / sample.width
        y = region["y"] / sample.height
        w = region["w"] / sample.width
        h = region["h"] / sample.height
        if self.augment:
            image = self.jitter(image)
            if self.allow_flip and random.random() < 0.5:
                image = TF.hflip(image)
                x = 1.0 - x - w
        box = torch.tensor([x, y, w, h], dtype=torch.float32)
        return self.normalize(image), box


class PieceHeatmapDataset(Dataset):
    def __init__(self, samples: list[Sample], augment: bool = True) -> None:
        self.samples = samples
        self.augment = augment
        self.jitter = transforms.ColorJitter(0.2, 0.2, 0.2, 0.04)
        self.normalize = transforms.Compose(
            [
                transforms.Resize((PIECE_INPUT, PIECE_INPUT)),
                transforms.ToTensor(),
                transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
            ]
        )

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        sample = self.samples[index]
        image = Image.open(sample.image_path).convert("RGB")
        game = sample.regions.get("game") or {
            "x": 0,
            "y": 0,
            "w": sample.width,
            "h": sample.height,
        }
        left = max(0, int(game["x"]))
        top = max(0, int(game["y"]))
        right = min(sample.width, left + max(1, int(game["w"])))
        bottom = min(sample.height, top + max(1, int(game["h"])))
        crop = image.crop((left, top, right, bottom))
        crop_w = max(1, right - left)
        crop_h = max(1, bottom - top)
        if self.augment:
            crop = self.jitter(crop)
        heat = torch.zeros(2, HEATMAP_SIZE, HEATMAP_SIZE, dtype=torch.float32)
        radius = torch.zeros(HEATMAP_SIZE, HEATMAP_SIZE, dtype=torch.float32)
        scale = min(crop_w, crop_h)
        for piece in sample.pieces:
            channel = KIND_CHANNELS.get(str(piece.get("kind")))
            if channel is None:
                continue
            cx = (int(piece["x"]) - left) / crop_w * HEATMAP_SIZE
            cy = (int(piece["y"]) - top) / crop_h * HEATMAP_SIZE
            r_hm = max(1.0, int(piece["r"]) / crop_w * HEATMAP_SIZE)
            draw_gaussian(heat[channel], cx, cy, max(1.0, r_hm / 2.2))
            ix = min(max(int(cx), 0), HEATMAP_SIZE - 1)
            iy = min(max(int(cy), 0), HEATMAP_SIZE - 1)
            radius[iy, ix] = min(1.0, int(piece["r"]) / scale)
        return self.normalize(crop), heat, radius


class CoinDigitDataset(Dataset):
    def __init__(self, samples: list[Sample], key: str = "coin", augment: bool = True) -> None:
        self.samples = samples
        self.key = key
        self.augment = augment
        self.jitter = transforms.ColorJitter(0.2, 0.2, 0.2, 0.04)
        self.normalize = transforms.Compose(
            [
                transforms.Resize((DIGIT_HEIGHT, DIGIT_WIDTH)),
                transforms.ToTensor(),
                transforms.Normalize(DIGIT_MEAN, DIGIT_STD),
            ]
        )

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        sample = self.samples[index]
        key = self.key
        digits = "".join(char for char in str(sample.readings.get(key) or "") if char.isdigit())
        box = dict(sample.regions[key])
        if self.augment and key == "coin":
            width = max(1, int(box["w"]))
            height = max(1, int(box["h"]))
            box["x"] = int(box["x"]) + random.randint(-max(2, width // 16), max(2, width // 16))
            box["y"] = int(box["y"]) + random.randint(-max(1, height // 12), max(1, height // 12))
            box["w"] = width + random.randint(-max(2, width // 20), max(2, width // 20))
            box["h"] = height + random.randint(-max(1, height // 12), max(1, height // 12))
        crop = crop_box(sample.image_path, box)
        if self.augment:
            crop = self.jitter(crop)
        crop = prepare_digit_crop(crop, key)
        return self.normalize(crop), encode_digits(digits, key=key)


class SceneDataset(Dataset):
    def __init__(self, samples: list[Sample], augment: bool = True) -> None:
        self.samples = samples
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
        return len(self.samples)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        sample = self.samples[index]
        image = Image.open(sample.image_path).convert("RGB")
        if self.augment:
            image = self.jitter(image)
            if random.random() < 0.5:
                image = TF.hflip(image)
        label = scene_index(sample.confirmed)
        return self.normalize(image), torch.tensor(label, dtype=torch.long)


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

    def __init__(
        self,
        jobs: list[tuple[str, list[Sample], Path]],
        epochs: int = TRAIN_EPOCHS,
    ) -> None:
        super().__init__()
        self.jobs = jobs
        self.epochs = epochs

    def run(self) -> None:
        metrics = None
        error: str | None = None
        try:
            self.progress.emit(1, max(len(self.jobs), 1) * 1000, "学習中です  準備しています")
            self.msleep(1)
            metrics = self._train()
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
        finally:
            self._release_cuda()
        if error:
            self.failed.emit(error)
        elif metrics is not None:
            self.finished_ok.emit(metrics)

    def _release_cuda(self) -> None:
        if not torch.cuda.is_available():
            return
        try:
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
        except Exception:
            pass

    def _raise_if_cancelled(self) -> None:
        if self.isInterruptionRequested():
            raise TrainingCancelled()

    def _emit_job_progress(
        self,
        job_index: int,
        epoch: int,
        batch_index: int,
        batches: int,
        message: str,
    ) -> None:
        frac = ((epoch - 1) + batch_index / max(batches, 1)) / max(self.epochs, 1)
        step = int(round((job_index + min(1.0, frac)) * 1000))
        total = max(len(self.jobs), 1) * 1000
        self.progress.emit(max(1, step), total, message)
        self.msleep(1)

    def _train(self) -> dict:
        if not self.jobs:
            raise ValueError(f"学習にはラベル済み画像が {MIN_TRAIN_SAMPLES} 枚以上必要です")
        results = []
        total_steps = self.epochs * len(self.jobs)
        try:
            for job_index, item in enumerate(self.jobs):
                self._raise_if_cancelled()
                key, samples, model_path = item[0], item[1], item[2]
                if len(item) > 3 and item[3]:
                    label = item[3]
                elif key == "pieces":
                    label = "ツム・ボム"
                else:
                    label = REGION_LABELS.get(key, key)
                self._emit_job_progress(
                    job_index,
                    1,
                    0,
                    1,
                    f"学習中です  {label}  準備しています",
                )
                if key == "pieces":
                    result = self._train_pieces(samples, model_path, job_index, total_steps, label)
                elif key == "coin_digits":
                    digit_saved = False
                    for box_key, filename, digit_label in (
                        ("coin", "coin_digits.pt", "coin の数字"),
                        ("result_coin", "result_coin_digits.pt", "result の数字"),
                    ):
                        part = [
                            sample
                            for sample in samples
                            if box_key in sample.confirmed
                            and sample.regions.get(box_key)
                            and "".join(
                                char
                                for char in str(sample.readings.get(box_key) or "")
                                if char.isdigit()
                            )
                        ]
                        if len(part) < MIN_TRAIN_SAMPLES:
                            continue
                        result = self._train_digits(
                            part,
                            model_path.parent / filename,
                            job_index,
                            total_steps,
                            digit_label,
                            box_key,
                        )
                        results.append(result)
                        digit_saved = True
                    if not digit_saved:
                        raise ValueError(f"「{label}」の学習には {MIN_TRAIN_SAMPLES} 枚以上必要です")
                    continue
                elif key == "scene":
                    result = self._train_scene(samples, model_path, job_index, total_steps, label)
                else:
                    result = self._train_one(key, samples, model_path, job_index, total_steps, label)
                results.append(result)
        except TrainingCancelled:
            return {"results": results, "cancelled": True, "epochs": self.epochs}
        return {"results": results, "cancelled": False, "epochs": self.epochs}

    def _train_one(
        self,
        key: str,
        samples: list[Sample],
        model_path: Path,
        job_index: int,
        total_steps: int,
        label: str,
    ) -> dict:
        if len(samples) < MIN_TRAIN_SAMPLES:
            raise ValueError(f"「{label}」の学習には {MIN_TRAIN_SAMPLES} 枚以上必要です")

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        dataset = RegionBoxDataset(samples, key, augment=True)
        eval_set = RegionBoxDataset(samples, key, augment=False)
        loader = DataLoader(
            dataset,
            batch_size=min(4, len(dataset)),
            shuffle=True,
            num_workers=0,
        )
        previous = _checkpoint(model_path)
        prev_state = previous.get("state_dict")
        model = GameRegionNet(pretrained=not bool(prev_state))
        if prev_state:
            try:
                model.load_state_dict(prev_state)
            except Exception:
                prev_state = None
                model = GameRegionNet()
        model.freeze_backbone(train_last_block=True)
        model.to(device)

        def eval_iou() -> float:
            model.eval()
            total_iou = 0.0
            with torch.no_grad():
                for index in range(len(eval_set)):
                    image, box = eval_set[index]
                    pred = model(image.unsqueeze(0).to(device))
                    total_iou += box_iou(pred, box.unsqueeze(0).to(device)).sum().item()
            return total_iou / max(len(eval_set), 1)

        prev_iou = eval_iou() if prev_state else None
        trainable = [p for p in model.parameters() if p.requires_grad]
        lr = 3e-4 if prev_state else 1e-3
        optimizer = torch.optim.AdamW(trainable, lr=lr, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=self.epochs)
        loss_fn = torch.nn.SmoothL1Loss()

        best_iou = -1.0
        best_state = None
        model_path.parent.mkdir(parents=True, exist_ok=True)

        for epoch in range(1, self.epochs + 1):
            self._raise_if_cancelled()
            model.train()
            total_loss = 0.0
            seen = 0
            batches = max(len(loader), 1)
            for batch_index, (images, boxes) in enumerate(loader, start=1):
                self._raise_if_cancelled()
                images = images.to(device)
                boxes = boxes.to(device)
                optimizer.zero_grad(set_to_none=True)
                preds = model(images)
                loss = loss_fn(preds, boxes)
                loss.backward()
                optimizer.step()
                batch = images.size(0)
                total_loss += loss.item() * batch
                seen += batch
                self._emit_job_progress(
                    job_index,
                    epoch,
                    batch_index,
                    batches,
                    f"学習中です  {label}  {epoch}/{self.epochs}  （{batch_index}/{batches}）",
                )
            scheduler.step()
            mean_iou = eval_iou()
            if mean_iou > best_iou:
                best_iou = mean_iou
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            self._emit_job_progress(
                job_index,
                epoch,
                batches,
                batches,
                f"学習中です  {label}  {epoch}/{self.epochs}  IoU {mean_iou:.3f}",
            )
            self._raise_if_cancelled()

        if best_state is None:
            raise RuntimeError(f"「{label}」の学習結果を保存できませんでした")
        if prev_iou is not None and best_iou < float(prev_iou):
            best_iou = float(prev_iou)
        else:
            torch.save(
                {"state_dict": best_state, "iou": best_iou, "key": key, "samples": len(samples)},
                model_path,
            )
        return {
            "key": key,
            "label": label,
            "iou": float(best_iou),
            "samples": len(samples),
        }

    def _train_pieces(
        self,
        samples: list[Sample],
        model_path: Path,
        job_index: int,
        total_steps: int,
        label: str,
    ) -> dict:
        if len(samples) < MIN_TRAIN_SAMPLES:
            raise ValueError(f"「{label}」の学習には {MIN_TRAIN_SAMPLES} 枚以上必要です")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        dataset = PieceHeatmapDataset(samples, augment=True)
        loader = DataLoader(
            dataset,
            batch_size=min(4, len(dataset)),
            shuffle=True,
            num_workers=0,
        )
        model = PieceNet()
        model.freeze_backbone()
        model.to(device)
        trainable = [p for p in model.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(trainable, lr=1e-3, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=self.epochs)
        best_loss = 10**9
        best_state = None
        model_path.parent.mkdir(parents=True, exist_ok=True)
        for epoch in range(1, self.epochs + 1):
            self._raise_if_cancelled()
            model.train()
            total_loss = 0.0
            seen = 0
            batches = max(len(loader), 1)
            for batch_index, (images, heat_t, radius_t) in enumerate(loader, start=1):
                self._raise_if_cancelled()
                images = images.to(device)
                heat_t = heat_t.to(device)
                radius_t = radius_t.to(device)
                optimizer.zero_grad(set_to_none=True)
                heat_p, radius_p = model(images)
                heat_loss = torch.nn.functional.mse_loss(heat_p, heat_t)
                mask = heat_t.max(dim=1).values > 0.4
                if mask.any():
                    radius_loss = torch.nn.functional.l1_loss(radius_p[:, 0][mask], radius_t[mask])
                else:
                    radius_loss = heat_p.sum() * 0.0
                loss = heat_loss * 8 + radius_loss
                loss.backward()
                optimizer.step()
                batch = images.size(0)
                total_loss += loss.item() * batch
                seen += batch
                self._emit_job_progress(
                    job_index,
                    epoch,
                    batch_index,
                    batches,
                    f"学習中です  {label}  {epoch}/{self.epochs}  （{batch_index}/{batches}）",
                )
            scheduler.step()
            mean_loss = total_loss / max(seen, 1)
            if mean_loss < best_loss:
                best_loss = mean_loss
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            self._emit_job_progress(
                job_index,
                epoch,
                batches,
                batches,
                f"学習中です  {label}  {epoch}/{self.epochs}  loss {mean_loss:.4f}",
            )
            self._raise_if_cancelled()
        if best_state is None:
            raise RuntimeError(f"「{label}」の学習結果を保存できませんでした")
        torch.save(
            {"state_dict": best_state, "loss": best_loss, "key": "pieces", "samples": len(samples)},
            model_path,
        )
        return {
            "key": "pieces",
            "label": label,
            "iou": max(0.0, 1.0 - float(best_loss)),
            "loss": float(best_loss),
            "samples": len(samples),
        }

    def _train_digits(
        self,
        samples: list[Sample],
        model_path: Path,
        job_index: int,
        total_steps: int,
        label: str,
        box_key: str = "coin",
    ) -> dict:
        if len(samples) < MIN_TRAIN_SAMPLES:
            raise ValueError(f"「{label}」の学習には {MIN_TRAIN_SAMPLES} 枚以上必要です")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        dataset = CoinDigitDataset(samples, key=box_key, augment=True)
        eval_set = CoinDigitDataset(samples, key=box_key, augment=False)
        loader = DataLoader(
            dataset,
            batch_size=min(4, len(dataset)),
            shuffle=True,
            num_workers=0,
        )
        previous = _checkpoint(model_path)
        prev_state = previous.get("state_dict")
        layout = digit_layout_for_key(box_key)
        if previous.get("layout") != layout:
            prev_state = None
        model = CoinDigitNet(pretrained=not bool(prev_state))
        if prev_state:
            try:
                model.load_state_dict(prev_state)
            except Exception:
                prev_state = None
                model = CoinDigitNet()
        model.to(device)

        def eval_acc() -> float:
            model.eval()
            exact = 0
            with torch.no_grad():
                for index in range(len(eval_set)):
                    image, target = eval_set[index]
                    logits = model(image.unsqueeze(0).to(device))
                    exact += int(
                        decode_logits(logits[0].detach().cpu()) == decode_indices(target)
                    )
            return exact / max(len(eval_set), 1)

        prev_acc = eval_acc() if prev_state else None
        if prev_acc is not None and prev_acc < 0.5:
            prev_state = None
            prev_acc = None
            model = CoinDigitNet()
            model.to(device)
        trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
        lr = 3e-4 if prev_state else 1e-3
        optimizer = torch.optim.AdamW(trainable, lr=lr, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=self.epochs)
        loss_fn = torch.nn.CrossEntropyLoss()
        best_acc = -1.0
        best_state = None
        model_path.parent.mkdir(parents=True, exist_ok=True)
        for epoch in range(1, self.epochs + 1):
            self._raise_if_cancelled()
            model.train()
            total_loss = 0.0
            seen = 0
            batches = max(len(loader), 1)
            for batch_index, (images, targets) in enumerate(loader, start=1):
                self._raise_if_cancelled()
                images = images.to(device)
                targets = targets.to(device)
                optimizer.zero_grad(set_to_none=True)
                logits = model(images)
                loss = loss_fn(logits.reshape(-1, logits.size(-1)), targets.reshape(-1))
                loss.backward()
                optimizer.step()
                batch = images.size(0)
                total_loss += loss.item() * batch
                seen += batch
                self._emit_job_progress(
                    job_index,
                    epoch,
                    batch_index,
                    batches,
                    f"学習中です  {label}  {epoch}/{self.epochs}  （{batch_index}/{batches}）",
                )
            scheduler.step()
            acc = eval_acc()
            if acc >= best_acc:
                best_acc = acc
                best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
            self._emit_job_progress(
                job_index,
                epoch,
                batches,
                batches,
                f"学習中です  {label}  {epoch}/{self.epochs}  acc {acc:.3f}",
            )
            self._raise_if_cancelled()
        if best_state is None:
            raise RuntimeError(f"「{label}」の学習結果を保存できませんでした")
        if prev_acc is not None and best_acc < float(prev_acc):
            best_acc = float(prev_acc)
        else:
            torch.save(
                {
                    "state_dict": best_state,
                    "acc": best_acc,
                    "key": box_key,
                    "samples": len(samples),
                    "layout": layout,
                },
                model_path,
            )
        return {
            "key": "coin_digits",
            "label": label,
            "iou": float(best_acc),
            "samples": len(samples),
        }

    def _train_scene(
        self,
        samples: list[Sample],
        model_path: Path,
        job_index: int,
        total_steps: int,
        label: str,
    ) -> dict:
        if len(samples) < MIN_TRAIN_SAMPLES:
            raise ValueError(f"「{label}」の学習には {MIN_TRAIN_SAMPLES} 枚以上必要です")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        dataset = SceneDataset(samples, augment=True)
        loader = DataLoader(
            dataset,
            batch_size=min(8, len(dataset)),
            shuffle=True,
            num_workers=0,
        )
        model = SceneNet()
        model.freeze_backbone(train_last_block=True)
        model.to(device)
        trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
        optimizer = torch.optim.AdamW(trainable, lr=1e-3, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=self.epochs)
        class_counts = [0, 0, 0]
        for sample in samples:
            class_counts[scene_index(sample.confirmed)] += 1
        weights = torch.tensor(
            [1.0 / max(count, 1) for count in class_counts],
            dtype=torch.float32,
            device=device,
        )
        weights = weights / weights.sum() * len(class_counts)
        loss_fn = torch.nn.CrossEntropyLoss(weight=weights)
        best_acc = -1.0
        best_state = None
        model_path.parent.mkdir(parents=True, exist_ok=True)
        for epoch in range(1, self.epochs + 1):
            self._raise_if_cancelled()
            model.train()
            total_loss = 0.0
            total_correct = 0
            seen = 0
            batches = max(len(loader), 1)
            for batch_index, (images, targets) in enumerate(loader, start=1):
                self._raise_if_cancelled()
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
                self._emit_job_progress(
                    job_index,
                    epoch,
                    batch_index,
                    batches,
                    f"学習中です  {label}  {epoch}/{self.epochs}  （{batch_index}/{batches}）",
                )
            scheduler.step()
            mean_loss = total_loss / max(seen, 1)
            acc = total_correct / max(seen, 1)
            if acc > best_acc:
                best_acc = acc
                best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            self._emit_job_progress(
                job_index,
                epoch,
                batches,
                batches,
                f"学習中です  {label}  {epoch}/{self.epochs}  acc {acc:.3f}",
            )
            self._raise_if_cancelled()
        if best_state is None:
            raise RuntimeError(f"「{label}」の学習結果を保存できませんでした")
        torch.save(
            {"state_dict": best_state, "acc": best_acc, "key": "scene", "samples": len(samples)},
            model_path,
        )
        return {
            "key": "scene",
            "label": label,
            "iou": float(best_acc),
            "samples": len(samples),
        }
