from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import torch
from PIL import Image
from PySide6.QtCore import QThread, Signal
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms

from app.coin_read import _load
from app.data_sync import trainer_data_dir

MIN_DIGIT_SAMPLES = 5
DIGIT_EPOCHS = 20
BOX_EPOCHS = 20


def _index_path() -> Path:
    return trainer_data_dir() / "index.json"


def _images_dir() -> Path:
    return trainer_data_dir() / "images"


def _models_dir() -> Path:
    return trainer_data_dir() / "models"


def _digits_only(text: str) -> str:
    return "".join(char for char in (text or "") if char.isdigit())


_taught_by_id: dict[str, set[str]] | None = None
_taught_index_mtime: float | None = None


def _invalidate_taught_cache() -> None:
    global _taught_by_id, _taught_index_mtime
    _taught_by_id = None
    _taught_index_mtime = None


def _taught_by_sample_id() -> dict[str, set[str]]:
    global _taught_by_id, _taught_index_mtime
    path = _index_path()
    mtime = path.stat().st_mtime if path.is_file() else None
    if _taught_by_id is not None and mtime == _taught_index_mtime:
        return _taught_by_id
    mapping: dict[str, set[str]] = {}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        for sample in payload.get("samples") or []:
            if sample.get("status") == "skipped":
                continue
            sample_id = str(sample.get("id") or "")
            if not sample_id:
                continue
            regions = sample.get("regions") or {}
            readings = sample.get("readings") or {}
            keys = {
                key
                for key in ("coin", "result_coin")
                if regions.get(key) and _digits_only(str(readings.get(key) or ""))
            }
            if keys:
                mapping[sample_id] = keys
    _taught_by_id = mapping
    _taught_index_mtime = mtime
    return mapping


def taught_keys_for_image(image_path: Path) -> set[str]:
    if not image_path.is_file():
        return set()
    try:
        sample_id = sha256(image_path.read_bytes()).hexdigest()[:12]
    except OSError:
        return set()
    return set(_taught_by_sample_id().get(sample_id, set()))


def _video_key(path: Path | str) -> str:
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(path)


def _load_index_samples() -> list[dict]:
    path = _index_path()
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return list(payload.get("samples") or [])


def taught_coin_for_image(image_path: Path, key: str) -> tuple[dict[str, int] | None, str]:
    if key not in {"coin", "result_coin"} or not image_path.is_file():
        return None, ""
    try:
        sample_id = sha256(image_path.read_bytes()).hexdigest()[:12]
    except OSError:
        return None, ""
    for sample in _load_index_samples():
        if str(sample.get("id") or "") != sample_id:
            continue
        digits = _digits_only(str((sample.get("readings") or {}).get(key) or ""))
        if not digits:
            return None, ""
        box = (sample.get("regions") or {}).get(key)
        cleaned = None
        if isinstance(box, dict):
            cleaned = {
                "x": int(box["x"]),
                "y": int(box["y"]),
                "w": max(1, int(box["w"])),
                "h": max(1, int(box["h"])),
            }
        return cleaned, digits
    return None, ""


def taught_coin_for_frame(
    video_path: Path | str | None,
    frame: int,
    key: str,
    frame_slack: int = 8,
) -> tuple[dict[str, int] | None, str]:
    if key not in {"coin", "result_coin"} or video_path is None:
        return None, ""
    want = _video_key(video_path)
    best: dict | None = None
    best_dist = None
    for sample in _load_index_samples():
        if sample.get("status") == "skipped":
            continue
        source = sample.get("source_video")
        if not source or _video_key(source) != want:
            continue
        digits = _digits_only(str((sample.get("readings") or {}).get(key) or ""))
        if not digits:
            continue
        try:
            src_frame = int(sample.get("source_frame"))
        except (TypeError, ValueError):
            continue
        dist = abs(src_frame - int(frame))
        if best_dist is None or dist < best_dist:
            best = sample
            best_dist = dist
    if best is None or best_dist is None or best_dist > max(int(frame_slack), 0):
        return None, ""
    digits = _digits_only(str((best.get("readings") or {}).get(key) or ""))
    box = (best.get("regions") or {}).get(key)
    cleaned = None
    if isinstance(box, dict):
        cleaned = {
            "x": int(box["x"]),
            "y": int(box["y"]),
            "w": max(1, int(box["w"])),
            "h": max(1, int(box["h"])),
        }
    return cleaned, digits


def digit_teaching_count() -> int:
    path = _index_path()
    if not path.is_file():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    count = 0
    for sample in payload.get("samples") or []:
        if sample.get("status") == "skipped":
            continue
        regions = sample.get("regions") or {}
        readings = sample.get("readings") or {}
        if any(
            regions.get(key) and _digits_only(str(readings.get(key) or ""))
            for key in ("coin", "result_coin")
        ):
            count += 1
    return count


def save_coin_teaching(
    image_path: Path,
    box: dict[str, int],
    key: str,
    number: str,
    source_video: Path | str | None = None,
    source_frame: int | None = None,
) -> int:
    digits = _digits_only(number)
    if not digits:
        raise ValueError("数字を入力してください")
    if not image_path.is_file():
        raise ValueError("画像がありません")
    cleaned = {
        "x": int(box["x"]),
        "y": int(box["y"]),
        "w": max(1, int(box["w"])),
        "h": max(1, int(box["h"])),
    }
    data = image_path.read_bytes()
    sample_id = sha256(data).hexdigest()[:12]
    ext = image_path.suffix.lower() if image_path.suffix else ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        ext = ".png"
    images = _images_dir()
    images.mkdir(parents=True, exist_ok=True)
    dest = images / f"{sample_id}{ext}"
    if not dest.exists():
        dest.write_bytes(data)
    with Image.open(dest) as image:
        width, height = image.size
    index_path = _index_path()
    payload: dict = {"samples": []}
    if index_path.is_file():
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {"samples": []}
    samples = payload.get("samples") or []
    existing = next((item for item in samples if item.get("id") == sample_id), None)
    if existing is None:
        existing = {
            "id": sample_id,
            "image": dest.name,
            "source_name": image_path.name,
            "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "width": width,
            "height": height,
            "game_region": None,
            "regions": {},
            "confirmed": [],
            "pieces": [],
            "readings": {},
            "status": "labeled",
        }
        samples.append(existing)
    regions = existing.setdefault("regions", {})
    regions[key] = cleaned
    confirmed = existing.setdefault("confirmed", [])
    if key not in confirmed:
        confirmed.append(key)
    readings = existing.setdefault("readings", {})
    readings[key] = digits
    existing["status"] = "labeled"
    if source_video is not None:
        existing["source_video"] = _video_key(source_video)
    if source_frame is not None:
        existing["source_frame"] = int(source_frame)
    payload["samples"] = samples
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _invalidate_taught_cache()
    return digit_teaching_count()


COIN_KIND_LABELS = {"coin": "coin", "result_coin": "result"}


def coin_teaching_counts() -> dict[str, int]:
    counts = {"coin": 0, "result_coin": 0}
    path = _index_path()
    if not path.is_file():
        return counts
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return counts
    for sample in payload.get("samples") or []:
        if sample.get("status") == "skipped":
            continue
        regions = sample.get("regions") or {}
        readings = sample.get("readings") or {}
        for key in ("coin", "result_coin"):
            if regions.get(key) or _digits_only(str(readings.get(key) or "")):
                counts[key] += 1
    return counts


def list_coin_teaching(key: str) -> list[dict]:
    items: list[dict] = []
    path = _index_path()
    if not path.is_file():
        return items
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return items
    for sample in payload.get("samples") or []:
        if sample.get("status") == "skipped":
            continue
        sample_id = str(sample.get("id") or "")
        image = _images_dir() / str(sample.get("image") or "")
        if not sample_id or not image.is_file():
            continue
        regions = sample.get("regions") or {}
        readings = sample.get("readings") or {}
        box = regions.get(key)
        digits = _digits_only(str(readings.get(key) or ""))
        if not box and not digits:
            continue
        cleaned = None
        if box:
            cleaned = {
                "x": int(box["x"]),
                "y": int(box["y"]),
                "w": max(1, int(box["w"])),
                "h": max(1, int(box["h"])),
            }
        items.append(
            {
                "id": sample_id,
                "path": image,
                "key": key,
                "box": cleaned,
                "digits": digits,
                "name": str(sample.get("source_name") or image.name),
            }
        )
    return items


def update_coin_teaching(
    sample_id: str,
    key: str,
    *,
    box: dict[str, int] | None = None,
    number: str | None = None,
) -> int:
    if key not in {"coin", "result_coin"}:
        raise ValueError("種類が違います")
    if box is None and number is None:
        raise ValueError("直す内容がありません")
    digits = None
    if number is not None:
        digits = _digits_only(number)
        if not digits:
            raise ValueError("数字を入力してください")
    cleaned = None
    if box is not None:
        cleaned = {
            "x": int(box["x"]),
            "y": int(box["y"]),
            "w": max(1, int(box["w"])),
            "h": max(1, int(box["h"])),
        }
    path = _index_path()
    if not path.is_file():
        raise ValueError("学習データがありません")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("学習データを読めませんでした") from exc
    samples = payload.get("samples") or []
    existing = next((item for item in samples if item.get("id") == sample_id), None)
    if existing is None:
        raise ValueError("この画像は学習データにありません")
    regions = existing.setdefault("regions", {})
    readings = existing.setdefault("readings", {})
    confirmed = existing.setdefault("confirmed", [])
    if cleaned is not None:
        regions[key] = cleaned
    if digits is not None:
        readings[key] = digits
        if not regions.get(key):
            raise ValueError("枠がありません。先に数字を囲んでください。")
    if regions.get(key) and _digits_only(str(readings.get(key) or "")):
        if key not in confirmed:
            confirmed.append(key)
        existing["status"] = "labeled"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _invalidate_taught_cache()
    return digit_teaching_count()


def remove_coin_teaching(sample_id: str, key: str) -> bool:
    path = _index_path()
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    samples = payload.get("samples") or []
    existing = next((item for item in samples if item.get("id") == sample_id), None)
    if existing is None:
        return False
    regions = existing.setdefault("regions", {})
    readings = existing.setdefault("readings", {})
    confirmed = existing.setdefault("confirmed", [])
    regions.pop(key, None)
    readings.pop(key, None)
    existing["confirmed"] = [item for item in confirmed if item != key]
    still = any(
        regions.get(item) or _digits_only(str(readings.get(item) or ""))
        for item in ("coin", "result_coin")
    )
    if not still:
        existing["status"] = "skipped"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _invalidate_taught_cache()
    return True


DIGIT_MODEL_FILES = (
    ("coin", "coin_digits.pt", "coin の数字"),
    ("result_coin", "result_coin_digits.pt", "result の数字"),
)


def _box_model_name(key: str) -> str:
    return "coin.pt" if key == "coin" else f"{key}.pt"


def _digit_items(key: str) -> list[tuple[Path, dict[str, int], str]]:
    path = _index_path()
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    items: list[tuple[Path, dict[str, int], str]] = []
    for sample in payload.get("samples") or []:
        if sample.get("status") in {"skipped", "predicted"}:
            continue
        image = _images_dir() / str(sample.get("image") or "")
        if not image.is_file():
            continue
        box = (sample.get("regions") or {}).get(key)
        digits = _digits_only(str((sample.get("readings") or {}).get(key) or ""))
        confirmed = sample.get("confirmed") or []
        if key not in confirmed or not box or not digits:
            continue
        items.append(
            (
                image,
                {
                    "x": int(box["x"]),
                    "y": int(box["y"]),
                    "w": int(box["w"]),
                    "h": int(box["h"]),
                },
                digits,
            )
        )
    return items


def digit_train_counts() -> dict[str, int]:
    return {key: len(_digit_items(key)) for key, _filename, _label in DIGIT_MODEL_FILES}


class _CropSet(Dataset):
    def __init__(
        self,
        items: list[tuple[Path, dict[str, int], str]],
        digit_mod,
        key: str = "coin",
        augment: bool = True,
    ) -> None:
        self.items = items
        self.digit_mod = digit_mod
        self.key = key
        self.augment = augment
        self.hud = _load("_tsum_hud_number", "hud_number.py")
        self.jitter = transforms.ColorJitter(0.2, 0.2, 0.2, 0.04)
        self.normalize = transforms.Compose(
            [
                transforms.Resize((digit_mod.DIGIT_HEIGHT, digit_mod.DIGIT_WIDTH)),
                transforms.ToTensor(),
                transforms.Normalize(digit_mod.IMAGENET_MEAN, digit_mod.IMAGENET_STD),
            ]
        )

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        path, box, digits = self.items[index]
        with Image.open(path) as image:
            rgb = image.convert("RGB")
        left = int(box["x"])
        top = int(box["y"])
        width = max(1, int(box["w"]))
        height = max(1, int(box["h"]))
        if self.augment and self.key == "coin":
            left += random.randint(-max(2, width // 16), max(2, width // 16))
            top += random.randint(-max(1, height // 12), max(1, height // 12))
            width += random.randint(-max(2, width // 20), max(2, width // 20))
            height += random.randint(-max(1, height // 12), max(1, height // 12))
        left = max(0, left)
        top = max(0, top)
        right = min(rgb.width, left + max(1, width))
        bottom = min(rgb.height, top + max(1, height))
        crop = rgb.crop((left, top, right, bottom))
        if self.augment and random.random() < 0.8:
            crop = self.jitter(crop)
        crop = self.hud.prepare_digit_crop(crop, self.key)
        return self.normalize(crop), self.digit_mod.encode_digits(digits, key=self.key)


class _BoxSet(Dataset):
    def __init__(self, items: list[tuple[Path, dict[str, int], str]], region_mod, augment: bool = True) -> None:
        self.items = items
        self.augment = augment
        self.jitter = transforms.ColorJitter(0.25, 0.25, 0.25, 0.05)
        self.normalize = transforms.Compose(
            [
                transforms.Resize((region_mod.INPUT_SIZE, region_mod.INPUT_SIZE)),
                transforms.ToTensor(),
                transforms.Normalize(region_mod.IMAGENET_MEAN, region_mod.IMAGENET_STD),
            ]
        )

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        path, box, _digits = self.items[index]
        with Image.open(path) as image:
            rgb = image.convert("RGB")
        width, height = rgb.size
        x = int(box["x"]) / max(width, 1)
        y = int(box["y"]) / max(height, 1)
        w = int(box["w"]) / max(width, 1)
        h = int(box["h"]) / max(height, 1)
        if self.augment:
            rgb = self.jitter(rgb)
        return self.normalize(rgb), torch.tensor([x, y, w, h], dtype=torch.float32)


def _box_iou(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
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


class DigitTrainWorker(QThread):
    progress = Signal(int, int, str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def run(self) -> None:
        try:
            jobs = []
            for key, filename, label in DIGIT_MODEL_FILES:
                items = _digit_items(key)
                if len(items) >= MIN_DIGIT_SAMPLES:
                    jobs.append((key, filename, label, items))
            if not jobs:
                counts = digit_train_counts()
                raise ValueError(
                    f"コイン数字の学習には {MIN_DIGIT_SAMPLES} 枚以上必要です。"
                    f"いま coin {counts['coin']} 枚、result {counts['result_coin']} 枚です。"
                )
            digit_mod = _load("_tsum_digit_model", "digit_model.py")
            region_mod = _load("_tsum_region_model", "model.py")
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            by_key: dict[str, dict] = {}
            step = BOX_EPOCHS + DIGIT_EPOCHS
            total_epochs = step * len(jobs)
            for job_index, (key, filename, label, items) in enumerate(jobs):
                box_label = "coin の枠" if key == "coin" else "result の枠"
                box_metrics = self._fit_box(
                    items,
                    _models_dir() / _box_model_name(key),
                    region_mod,
                    device,
                    key,
                    box_label,
                    job_index * step,
                    total_epochs,
                )
                if box_metrics is None:
                    return
                metrics = self._fit_one(
                    items,
                    _models_dir() / filename,
                    digit_mod,
                    device,
                    key,
                    label,
                    job_index * step + BOX_EPOCHS,
                    total_epochs,
                )
                if metrics is None:
                    return
                metrics["iou"] = box_metrics["iou"]
                metrics["box_kept"] = box_metrics["kept"]
                by_key[key] = metrics
            if device.type == "cuda":
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
            samples = sum(int(item["samples"]) for item in by_key.values())
            acc = by_key.get("coin", {}).get("acc")
            if acc is None:
                acc = next(iter(by_key.values()))["acc"]
            self.finished_ok.emit({"acc": float(acc), "samples": samples, "by_key": by_key})
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def _fit_box(
        self,
        items: list[tuple[Path, dict[str, int], str]],
        dest: Path,
        region_mod,
        device,
        key: str,
        label: str,
        epoch_offset: int,
        epoch_total: int,
    ) -> dict | None:
        previous = _checkpoint(dest)
        prev_state = previous.get("state_dict")
        dataset = _BoxSet(items, region_mod, augment=True)
        eval_set = _BoxSet(items, region_mod, augment=False)
        loader = DataLoader(dataset, batch_size=min(4, len(dataset)), shuffle=True, num_workers=0)
        model = region_mod.GameRegionNet(pretrained=not bool(prev_state))
        if prev_state:
            try:
                model.load_state_dict(prev_state)
            except Exception:
                prev_state = None
                model = region_mod.GameRegionNet()
        model.freeze_backbone(train_last_block=True)
        model.to(device)

        def eval_iou() -> float:
            model.eval()
            total = 0.0
            with torch.no_grad():
                for index in range(len(eval_set)):
                    image, box = eval_set[index]
                    pred = model(image.unsqueeze(0).to(device))
                    total += _box_iou(pred, box.unsqueeze(0).to(device)).sum().item()
            return total / max(len(eval_set), 1)

        prev_iou = eval_iou() if prev_state else None
        trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
        lr = 3e-4 if prev_state else 1e-3
        optimizer = torch.optim.AdamW(trainable, lr=lr, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=BOX_EPOCHS)
        loss_fn = torch.nn.SmoothL1Loss()
        best_iou = -1.0
        best_state = None
        dest.parent.mkdir(parents=True, exist_ok=True)
        for epoch in range(1, BOX_EPOCHS + 1):
            if self.isInterruptionRequested():
                self.failed.emit("中止")
                return None
            model.train()
            for images, boxes in loader:
                if self.isInterruptionRequested():
                    self.failed.emit("中止")
                    return None
                images = images.to(device)
                boxes = boxes.to(device)
                optimizer.zero_grad(set_to_none=True)
                preds = model(images)
                loss = loss_fn(preds, boxes)
                loss.backward()
                optimizer.step()
            scheduler.step()
            iou = eval_iou()
            if iou > best_iou:
                best_iou = iou
                best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
            self.progress.emit(
                epoch_offset + epoch,
                epoch_total,
                f"{label}を学習しています {epoch}/{BOX_EPOCHS}",
            )
        if best_state is None:
            raise RuntimeError("学習結果を保存できませんでした")
        kept = False
        if prev_iou is not None and best_iou < float(prev_iou):
            kept = True
            best_iou = float(prev_iou)
        else:
            torch.save(
                {"state_dict": best_state, "iou": best_iou, "key": key, "samples": len(items)},
                dest,
            )
        del model, optimizer, scheduler, loader, dataset
        if device.type == "cuda":
            torch.cuda.empty_cache()
        return {"iou": float(best_iou), "samples": len(items), "kept": kept}

    def _fit_one(
        self,
        items: list[tuple[Path, dict[str, int], str]],
        dest: Path,
        digit_mod,
        device,
        key: str,
        label: str,
        epoch_offset: int,
        epoch_total: int,
    ) -> dict | None:
        previous = _checkpoint(dest)
        prev_state = previous.get("state_dict")
        layout = digit_mod.digit_layout_for_key(key) if hasattr(digit_mod, "digit_layout_for_key") else getattr(digit_mod, "DIGIT_LAYOUT", "")
        if previous.get("layout") != layout:
            prev_state = None
        dataset = _CropSet(items, digit_mod, key=key, augment=True)
        eval_set = _CropSet(items, digit_mod, key=key, augment=False)
        loader = DataLoader(dataset, batch_size=min(4, len(dataset)), shuffle=True, num_workers=0)
        model = digit_mod.CoinDigitNet(pretrained=not bool(prev_state))
        if prev_state:
            try:
                model.load_state_dict(prev_state)
            except Exception:
                prev_state = None
                model = digit_mod.CoinDigitNet()
        model.to(device)

        def eval_acc() -> float:
            model.eval()
            exact = 0
            with torch.no_grad():
                for index in range(len(eval_set)):
                    image, target = eval_set[index]
                    logits = model(image.unsqueeze(0).to(device))
                    exact += int(
                        digit_mod.decode_logits(logits[0].detach().cpu())
                        == digit_mod.decode_indices(target)
                    )
            return exact / max(len(eval_set), 1)

        prev_acc = eval_acc() if prev_state else None
        if prev_acc is not None and prev_acc < 0.5:
            prev_state = None
            prev_acc = None
            model = digit_mod.CoinDigitNet()
            model.to(device)
        trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
        lr = 3e-4 if prev_state else 1e-3
        optimizer = torch.optim.AdamW(trainable, lr=lr, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=DIGIT_EPOCHS)
        loss_fn = torch.nn.CrossEntropyLoss()
        best_acc = -1.0
        best_state = None
        dest.parent.mkdir(parents=True, exist_ok=True)
        for epoch in range(1, DIGIT_EPOCHS + 1):
            if self.isInterruptionRequested():
                self.failed.emit("中止")
                return None
            model.train()
            for images, targets in loader:
                if self.isInterruptionRequested():
                    self.failed.emit("中止")
                    return None
                images = images.to(device)
                targets = targets.to(device)
                optimizer.zero_grad(set_to_none=True)
                logits = model(images)
                loss = loss_fn(logits.reshape(-1, logits.size(-1)), targets.reshape(-1))
                loss.backward()
                optimizer.step()
            scheduler.step()
            acc = eval_acc()
            if acc >= best_acc:
                best_acc = acc
                best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
            self.progress.emit(
                epoch_offset + epoch,
                epoch_total,
                f"{label}を学習しています {epoch}/{DIGIT_EPOCHS}",
            )
        if best_state is None:
            raise RuntimeError("学習結果を保存できませんでした")
        kept = False
        if prev_acc is not None and best_acc < float(prev_acc):
            kept = True
            best_acc = float(prev_acc)
        else:
            torch.save(
                {
                    "state_dict": best_state,
                    "acc": best_acc,
                    "key": key,
                    "samples": len(items),
                    "layout": layout,
                },
                dest,
            )
        del model, optimizer, scheduler, loader, dataset
        if device.type == "cuda":
            torch.cuda.empty_cache()
        return {"acc": float(best_acc), "samples": len(items), "kept": kept}
