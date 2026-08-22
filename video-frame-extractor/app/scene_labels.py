from __future__ import annotations

import json
import re
from pathlib import Path

from app.data_sync import (
    bundle_dir,
    labels_file,
    model_file,
    resolve_sample_path,
    store_image,
)

LABELS_PATH = bundle_dir() / "scene_labels.json"
SCENE_MODEL_PATH = bundle_dir() / "scene.pt"
MIN_SCENE_SAMPLES = 5
OTHER_KEY = "other"
OTHER_NAME = "どちらでもない"
DEFAULT_KINDS = (("go", "GO"), ("timeup", "TIME UP"))


def scene_model_path() -> Path:
    return model_file()


def scene_model_ready() -> bool:
    return scene_model_path().is_file()


def slug_key(name: str, used: set[str]) -> str:
    ascii_part = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    base = ascii_part or "scene"
    key = base
    index = 2
    while key in used or key == OTHER_KEY:
        key = f"{base}_{index}"
        index += 1
    return key


class SceneLabels:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or labels_file()
        self._kinds: list[tuple[str, str]] = list(DEFAULT_KINDS)
        self._items: list[dict[str, str]] = []
        self.reload()

    def reload(self) -> None:
        source = labels_file()
        self.path = bundle_dir() / "scene_labels.json"
        self._kinds = list(DEFAULT_KINDS)
        self._items = []
        if not source.exists():
            return
        raw = json.loads(source.read_text(encoding="utf-8"))
        kinds = []
        for item in raw.get("kinds") or []:
            key = str(item.get("key") or "").strip()
            name = str(item.get("name") or "").strip()
            if key and name and key != OTHER_KEY:
                kinds.append((key, name))
        if kinds:
            self._kinds = kinds
        allowed = set(self.classes())
        items = []
        root = source.parent
        for item in raw.get("samples") or []:
            kind = str(item.get("kind") or "")
            file_path = resolve_sample_path(str(item.get("path") or ""), root)
            if kind not in allowed or file_path is None:
                continue
            items.append({"path": str(file_path), "kind": kind})
        self._items = items

    def _save(self) -> None:
        dest = bundle_dir()
        dest.mkdir(parents=True, exist_ok=True)
        images_dir = dest / "images"
        used = {child.name for child in images_dir.iterdir()} if images_dir.is_dir() else set()
        packed = []
        items = []
        for item in self._items:
            src = resolve_sample_path(item["path"], dest)
            if src is None:
                continue
            relative = store_image(src, images_dir, used)
            if relative is None:
                continue
            packed.append({"path": relative, "kind": item["kind"]})
            stored = resolve_sample_path(relative, dest)
            if stored is not None:
                items.append({"path": str(stored), "kind": item["kind"]})
        self.path = dest / "scene_labels.json"
        self.path.write_text(
            json.dumps(
                {
                    "kinds": [{"key": key, "name": name} for key, name in self._kinds],
                    "samples": packed,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self._items = items

    def kinds(self) -> list[tuple[str, str]]:
        return list(self._kinds)

    def classes(self) -> tuple[str, ...]:
        return (OTHER_KEY, *[key for key, _name in self._kinds])

    def name_of(self, key: str) -> str:
        if key == OTHER_KEY:
            return OTHER_NAME
        for item_key, name in self._kinds:
            if item_key == key:
                return name
        return key

    def extract_keys(self) -> list[str]:
        return [key for key, _name in self._kinds]

    def extract_names(self) -> str:
        names = [name for _key, name in self._kinds]
        if not names:
            return "画面"
        if len(names) == 1:
            return names[0]
        return "と".join(names)

    def keys_named(self, *names: str) -> list[str]:
        aliases = {name.lower() for name in names}
        return [
            key
            for key, name in self._kinds
            if key.lower() in aliases or name.lower() in aliases
        ]

    def names_of(self, keys: list[str]) -> str:
        names = [self.name_of(key) for key in keys]
        if not names:
            return "画面"
        if len(names) == 1:
            return names[0]
        return "と".join(names)

    def add_kind(self, name: str) -> str:
        label = name.strip()
        if not label:
            raise ValueError("名前を入力してください")
        if any(existing == label for _key, existing in self._kinds) or label == OTHER_NAME:
            raise ValueError(f"「{label}」はすでにあります")
        key = slug_key(label, {item for item, _name in self._kinds})
        self._kinds.append((key, label))
        self._save()
        return key

    def add(self, image_path: Path, kind: str) -> None:
        self.add_many([image_path], kind)

    def add_many(self, image_paths: list[Path], kind: str) -> int:
        if kind not in self.classes():
            raise ValueError(kind)
        added = 0
        dest = bundle_dir()
        images_dir = dest / "images"
        used = {child.name for child in images_dir.iterdir()} if images_dir.is_dir() else set()
        by_path = {item["path"]: item for item in self._items}
        for image_path in image_paths:
            if not image_path.is_file():
                continue
            relative = store_image(image_path, images_dir, used)
            if relative is None:
                continue
            stored = resolve_sample_path(relative, dest)
            if stored is None:
                continue
            key = str(stored)
            if key in by_path:
                by_path[key]["kind"] = kind
            else:
                item = {"path": key, "kind": kind}
                self._items.append(item)
                by_path[key] = item
            added += 1
        if added:
            self._save()
        return added

    def counts(self) -> dict[str, int]:
        counts = {key: 0 for key in self.classes()}
        for item in self._items:
            counts[item["kind"]] = counts.get(item["kind"], 0) + 1
        return counts

    def items(self) -> list[dict[str, str]]:
        return list(self._items)

    def missing_for_train(self) -> list[str]:
        counts = self.counts()
        return [
            f"{self.name_of(key)} {counts.get(key, 0)} 枚"
            for key in self.classes()
            if counts.get(key, 0) < MIN_SCENE_SAMPLES
        ]

    def can_train(self) -> bool:
        return bool(self._kinds) and not self.missing_for_train()
