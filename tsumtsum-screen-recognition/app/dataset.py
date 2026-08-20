from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image
from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage, QPixmap

from app.paths import DATA_DIR, IMAGE_EXTENSIONS
from app.regions import PIECE_KEYS, REGION_KEYS, model_filename


@dataclass
class Sample:
    id: str
    image: str
    source_name: str
    added_at: str
    width: int
    height: int
    game_region: dict[str, int] | None
    regions: dict[str, dict[str, int]]
    confirmed: list[str]
    pieces: list[dict[str, int]]
    status: str  # unlabeled | predicted | labeled | skipped

    @property
    def image_path(self) -> Path:
        return DATA_DIR / "images" / self.image

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "image": self.image,
            "source_name": self.source_name,
            "added_at": self.added_at,
            "width": self.width,
            "height": self.height,
            "game_region": self.game_region,
            "regions": self.regions,
            "confirmed": self.confirmed,
            "pieces": self.pieces,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Sample:
        regions = dict(data.get("regions") or {})
        game_region = data.get("game_region")
        if game_region and "game" not in regions:
            regions["game"] = game_region
        if "game" in regions:
            game_region = regions["game"]
        status = data.get("status", "unlabeled")
        if "confirmed" in data:
            confirmed = [str(key) for key in data.get("confirmed") or [] if key in regions]
        elif status == "labeled":
            confirmed = list(regions.keys())
        else:
            confirmed = []
        return cls(
            id=data["id"],
            image=data["image"],
            source_name=data.get("source_name", data["image"]),
            added_at=data.get("added_at", ""),
            width=int(data.get("width") or 0),
            height=int(data.get("height") or 0),
            game_region=game_region,
            regions=regions,
            confirmed=confirmed,
            pieces=[dict(item) for item in data.get("pieces") or []],
            status=status,
        )


class Dataset:
    def __init__(self, root: Path = DATA_DIR) -> None:
        self.root = root
        self.images_dir = root / "images"
        self.labels_dir = root / "labels"
        self.models_dir = root / "models"
        self.index_path = root / "index.json"
        self.model_path = self.models_dir / model_filename("game")
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.labels_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._samples: list[Sample] = []
        self._load()

    def reload(self) -> None:
        self._load()

    def _load(self) -> None:
        if not self.index_path.exists():
            self._samples = []
            return
        raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        self._samples = [Sample.from_dict(item) for item in raw.get("samples", [])]

    def _save(self) -> None:
        payload = {"samples": [sample.to_dict() for sample in self._samples]}
        self.index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def all(self) -> list[Sample]:
        return list(self._samples)

    def get(self, sample_id: str) -> Sample | None:
        return next((s for s in self._samples if s.id == sample_id), None)

    def labeled(self) -> list[Sample]:
        return [s for s in self._samples if s.status == "labeled" and s.game_region]

    def labeled_for(self, key: str) -> list[Sample]:
        if key in PIECE_KEYS:
            return [
                sample
                for sample in self._samples
                if sample.status != "skipped"
                and any(piece.get("kind") == key for piece in sample.pieces)
            ]
        return [
            sample
            for sample in self._samples
            if sample.status != "skipped" and key in sample.confirmed and sample.regions.get(key)
        ]

    def labeled_counts(self) -> dict[str, int]:
        return {key: len(self.labeled_for(key)) for key in [*REGION_KEYS, *PIECE_KEYS]}

    def model_path_for(self, key: str) -> Path:
        return self.models_dir / model_filename(key)

    def unlabeled(self) -> list[Sample]:
        return [s for s in self._samples if s.status == "unlabeled"]

    def pending(self) -> list[Sample]:
        return [s for s in self._samples if s.status in {"unlabeled", "predicted"}]

    def next_pending(self, after_id: str | None) -> str | None:
        pending_ids = {s.id for s in self.pending()}
        if not pending_ids:
            return None
        if after_id is None:
            return self.pending()[0].id
        ids = [s.id for s in self._samples]
        try:
            start = ids.index(after_id)
        except ValueError:
            return self.pending()[0].id
        for sample in self._samples[start + 1 :] + self._samples[: start + 1]:
            if sample.id in pending_ids and sample.id != after_id:
                return sample.id
        return None

    def counts(self) -> dict[str, int]:
        return {
            "total": len(self._samples),
            "labeled": len(self.labeled()),
            "predicted": sum(1 for s in self._samples if s.status == "predicted"),
            "unlabeled": len(self.unlabeled()),
            "skipped": sum(1 for s in self._samples if s.status == "skipped"),
        }

    def import_file(self, path: Path) -> Sample:
        data = path.read_bytes()
        ext = path.suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            ext = ".png"
        return self._import_bytes(data, ext, path.name)

    def import_qimage(self, image: QImage | QPixmap, source_name: str = "clipboard.png") -> Sample:
        if isinstance(image, QPixmap):
            image = image.toImage()
        if image is None or image.isNull():
            raise ValueError("空の画像です")
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        data = bytes(QByteArray(buffer.data()))
        return self._import_bytes(data, ".png", source_name)

    def _import_bytes(self, data: bytes, ext: str, source_name: str) -> Sample:
        digest = hashlib.sha256(data).hexdigest()[:12]
        existing = self.get(digest)
        if existing:
            return existing

        filename = f"{digest}{ext}"
        dest = self.images_dir / filename
        dest.write_bytes(data)

        with Image.open(dest) as img:
            width, height = img.size

        sample = Sample(
            id=digest,
            image=filename,
            source_name=source_name,
            added_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            width=width,
            height=height,
            game_region=None,
            regions={},
            confirmed=[],
            pieces=[],
            status="unlabeled",
        )
        self._samples.append(sample)
        self._save()
        return sample

    def set_regions(
        self,
        sample_id: str,
        regions: dict[str, dict[str, int]],
        status: str | None = None,
        pieces: list[dict[str, int]] | None = None,
    ) -> Sample:
        sample = self.get(sample_id)
        if sample is None:
            raise KeyError(sample_id)
        cleaned: dict[str, dict[str, int]] = {}
        for key, box in regions.items():
            cleaned[key] = {
                "x": int(box["x"]),
                "y": int(box["y"]),
                "w": int(box["w"]),
                "h": int(box["h"]),
            }
        sample.regions = cleaned
        sample.game_region = cleaned.get("game")
        if pieces is not None:
            sample.pieces = [
                {
                    "x": int(piece["x"]),
                    "y": int(piece["y"]),
                    "r": int(piece["r"]),
                    "kind": str(piece["kind"]),
                    "group": int(piece.get("group") or 1),
                }
                for piece in pieces
                if int(piece.get("r") or 0) >= 4
            ]
        kinds = {piece["kind"] for piece in sample.pieces}
        sample.confirmed = list(cleaned.keys()) + [key for key in PIECE_KEYS if key in kinds]
        if status is not None:
            sample.status = status
        elif sample.game_region:
            sample.status = "labeled"
        elif sample.status != "skipped":
            sample.status = "unlabeled"
        self._save()
        return sample

    def set_region(
        self,
        sample_id: str,
        x: int,
        y: int,
        w: int,
        h: int,
        status: str = "labeled",
        key: str = "game",
    ) -> Sample:
        sample = self.get(sample_id)
        if sample is None:
            raise KeyError(sample_id)
        box = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
        sample.regions[key] = box
        if key not in sample.confirmed:
            sample.confirmed.append(key)
        if key == "game":
            sample.game_region = box
            sample.status = status
        self._save()
        return sample

    def apply_predictions(self, sample_id: str, boxes: dict[str, dict[str, int]]) -> list[str]:
        sample = self.get(sample_id)
        if sample is None:
            raise KeyError(sample_id)
        added: list[str] = []
        confirmed = set(sample.confirmed)
        for key, box in boxes.items():
            if key in confirmed:
                continue
            sample.regions[key] = {
                "x": int(box["x"]),
                "y": int(box["y"]),
                "w": int(box["w"]),
                "h": int(box["h"]),
            }
            if key == "game":
                sample.game_region = sample.regions[key]
                if sample.status == "unlabeled":
                    sample.status = "predicted"
            added.append(key)
        if added:
            self._save()
        return added

    def clear_named_region(self, sample_id: str, key: str) -> Sample:
        sample = self.get(sample_id)
        if sample is None:
            raise KeyError(sample_id)
        sample.regions.pop(key, None)
        sample.confirmed = [item for item in sample.confirmed if item != key]
        if key in PIECE_KEYS:
            sample.pieces = [piece for piece in sample.pieces if piece.get("kind") != key]
        if key == "game":
            sample.game_region = None
            if sample.status != "skipped":
                sample.status = "unlabeled"
        self._save()
        return sample

    def confirm_region(self, sample_id: str) -> Sample:
        sample = self.get(sample_id)
        if sample is None or sample.game_region is None:
            raise KeyError(sample_id)
        if "game" not in sample.confirmed:
            sample.confirmed.append("game")
        sample.status = "labeled"
        self._save()
        return sample

    def clear_region(self, sample_id: str) -> Sample:
        sample = self.get(sample_id)
        if sample is None:
            raise KeyError(sample_id)
        sample.game_region = None
        sample.regions.pop("game", None)
        sample.confirmed = [item for item in sample.confirmed if item != "game"]
        sample.status = "unlabeled"
        self._save()
        return sample

    def skip(self, sample_id: str) -> Sample:
        sample = self.get(sample_id)
        if sample is None:
            raise KeyError(sample_id)
        sample.game_region = None
        sample.regions.pop("game", None)
        sample.confirmed = [item for item in sample.confirmed if item != "game"]
        sample.status = "skipped"
        self._save()
        return sample

    def remove(self, sample_id: str) -> None:
        sample = self.get(sample_id)
        if sample is None:
            return
        image_path = sample.image_path
        if image_path.exists():
            image_path.unlink()
        self._samples = [s for s in self._samples if s.id != sample_id]
        self._save()
