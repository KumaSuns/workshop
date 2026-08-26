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


def _digit_items(key: str) -> list[tuple[Path, dict[str, int], str]]:
    path = _index_path()
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    items: list[tuple[Path, dict[str, int], str]] = []
    for sample in payload.get("samples") or []:
        if sample.get("status") == "skipped":
            continue
        image = _images_dir() / str(sample.get("image") or "")
        if not image.is_file():
            continue
        box = (sample.get("regions") or {}).get(key)
        digits = _digits_only(str((sample.get("readings") or {}).get(key) or ""))
        if box and digits:
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
    def __init__(self, items: list[tuple[Path, dict[str, int], str]], digit_mod) -> None:
        self.items = items
        self.digit_mod = digit_mod
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
        left = max(0, int(box["x"]))
        top = max(0, int(box["y"]))
        right = min(rgb.width, left + max(1, int(box["w"])))
        bottom = min(rgb.height, top + max(1, int(box["h"])))
        crop = rgb.crop((left, top, right, bottom))
        if random.random() < 0.8:
            crop = self.jitter(crop)
        return self.normalize(crop), self.digit_mod.encode_digits(digits)


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
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            by_key: dict[str, dict] = {}
            total_epochs = DIGIT_EPOCHS * len(jobs)
            for job_index, (key, filename, label, items) in enumerate(jobs):
                metrics = self._fit_one(
                    items,
                    _models_dir() / filename,
                    digit_mod,
                    device,
                    key,
                    label,
                    job_index * DIGIT_EPOCHS,
                    total_epochs,
                )
                if metrics is None:
                    return
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
        dataset = _CropSet(items, digit_mod)
        loader = DataLoader(dataset, batch_size=min(4, len(dataset)), shuffle=True, num_workers=0)
        model = digit_mod.CoinDigitNet()
        model.to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=DIGIT_EPOCHS)
        best_acc = -1.0
        best_state = None
        dest.parent.mkdir(parents=True, exist_ok=True)
        for epoch in range(1, DIGIT_EPOCHS + 1):
            if self.isInterruptionRequested():
                self.failed.emit("中止")
                return None
            model.train()
            exact = 0
            seen = 0
            for images, targets in loader:
                if self.isInterruptionRequested():
                    self.failed.emit("中止")
                    return None
                images = images.to(device)
                targets = targets.to(device)
                optimizer.zero_grad(set_to_none=True)
                logits = model(images)
                loss = digit_mod.digit_ctc_loss(logits, targets)
                loss.backward()
                optimizer.step()
                for row, truth in zip(logits, targets):
                    exact += int(
                        digit_mod.decode_logits(row.detach().cpu())
                        == digit_mod.decode_indices(truth.detach().cpu())
                    )
                seen += images.size(0)
            scheduler.step()
            acc = exact / max(seen, 1)
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
        torch.save(
            {"state_dict": best_state, "acc": best_acc, "key": key, "samples": len(items)},
            dest,
        )
        del model, optimizer, scheduler, loader, dataset
        if device.type == "cuda":
            torch.cuda.empty_cache()
        return {"acc": float(best_acc), "samples": len(items)}
