from __future__ import annotations

import json
from pathlib import Path

from app.data_sync import (
    bundle_dir,
    labels_file,
    model_file,
    resolve_sample_path,
    store_image,
    image_names_in,
)
from app.paths import kind_folder_name

LABELS_PATH = bundle_dir() / "scene_labels.json"
SCENE_MODEL_PATH = bundle_dir() / "scene.pt"
MIN_SCENE_SAMPLES = 5
OTHER_KEY = "other"
OTHER_NAME = "どちらでもない"
DEFAULT_KINDS = (
    ("go", "GO"),
    ("timeup", "TIME UP"),
    ("item", "item"),
    ("result", "result"),
    ("coin", "coin"),
    ("fever", "fever"),
    ("skill", "skill"),
)
HIDDEN_FROM_RESULTS = {"raredy", "fever"}
IDLE_KINDS = {"skill"}


def scene_model_path() -> Path:
    return model_file()


def scene_model_ready() -> bool:
    return scene_model_path().is_file()


class SceneLabels:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or labels_file()
        self._kinds: list[tuple[str, str]] = list(DEFAULT_KINDS)
        self._hidden_from_results: set[str] = set(HIDDEN_FROM_RESULTS)
        self._items: list[dict[str, str]] = []
        self.reload()

    def reload(self) -> None:
        source = labels_file()
        self.path = bundle_dir() / "scene_labels.json"
        self._kinds = list(DEFAULT_KINDS)
        self._hidden_from_results = set(HIDDEN_FROM_RESULTS)
        self._items = []
        if not source.exists():
            self._ensure_default_kinds()
            self._ensure_hidden_kinds()
            return
        raw = json.loads(source.read_text(encoding="utf-8"))
        kinds = []
        hidden = set(HIDDEN_FROM_RESULTS)
        for item in raw.get("kinds") or []:
            key = str(item.get("key") or "").strip()
            name = str(item.get("name") or "").strip()
            if key and name and key != OTHER_KEY:
                kinds.append((key, name))
                if item.get("in_results") is False:
                    hidden.add(key)
                elif item.get("in_results") is True:
                    hidden.discard(key)
        if kinds:
            self._kinds = kinds
        self._hidden_from_results = hidden
        self._ensure_default_kinds()
        self._ensure_hidden_kinds()
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

    def _ensure_default_kinds(self) -> None:
        names = {key: name for key, name in DEFAULT_KINDS}
        self._kinds = [(key, names.get(key, name)) for key, name in self._kinds]
        have = {key for key, _name in self._kinds}
        missing = [(key, name) for key, name in DEFAULT_KINDS if key not in have]
        if not missing:
            return
        insert_at = next(
            (
                index
                for index, (key, _name) in enumerate(self._kinds)
                if key in self._hidden_from_results or key in HIDDEN_FROM_RESULTS
            ),
            len(self._kinds),
        )
        for offset, item in enumerate(missing):
            self._kinds.insert(insert_at + offset, item)

    def _ensure_hidden_kinds(self) -> None:
        have = {key for key, _name in self._kinds}
        for key in HIDDEN_FROM_RESULTS:
            if key not in have:
                self._kinds.append((key, key))
            self._hidden_from_results.add(key)

    def _save(self) -> None:
        dest = bundle_dir()
        dest.mkdir(parents=True, exist_ok=True)
        images_dir = dest / "images"
        used_by_kind: dict[str, set[str]] = {}
        packed = []
        items = []
        for item in self._items:
            src = resolve_sample_path(item["path"], dest)
            if src is None:
                continue
            kind = item["kind"]
            folder_name = kind_folder_name(kind)
            used = used_by_kind.setdefault(folder_name, image_names_in(images_dir / folder_name))
            relative = store_image(src, images_dir, used, kind)
            if relative is None:
                continue
            packed.append({"path": relative, "kind": item["kind"]})
            stored = resolve_sample_path(relative, dest)
            if stored is not None:
                items.append({"path": str(stored), "kind": item["kind"]})
        self._write_json(packed)
        self._items = items

    def _write_json(self, samples: list[dict[str, str]]) -> None:
        dest = bundle_dir()
        dest.mkdir(parents=True, exist_ok=True)
        self.path = dest / "scene_labels.json"
        self.path.write_text(
            json.dumps(
                {
                    "kinds": [
                        {
                            "key": key,
                            "name": name,
                            **({"in_results": False} if key in self._hidden_from_results else {}),
                        }
                        for key, name in self._kinds
                    ],
                    "samples": samples,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _sample_entry(self, item: dict[str, str]) -> dict[str, str]:
        dest = bundle_dir()
        src = resolve_sample_path(item["path"], dest)
        if src is None:
            return {"path": item["path"], "kind": item["kind"]}
        try:
            relative = src.resolve().relative_to(dest.resolve()).as_posix()
        except ValueError:
            relative = str(src)
        return {"path": relative, "kind": item["kind"]}

    def _save_items(self) -> None:
        self._write_json([self._sample_entry(item) for item in self._items])

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
        return [
            key
            for key, _name in self._kinds
            if key not in self._hidden_from_results and key not in IDLE_KINDS
        ]

    def correct_keys(self) -> list[str]:
        return [key for key, _name in self._kinds]

    def hidden_keys(self) -> list[str]:
        return [key for key, _name in self._kinds if key in self._hidden_from_results]

    def idle_keys(self) -> list[str]:
        return [key for key, _name in self._kinds if key in IDLE_KINDS]

    def train_classes(self) -> tuple[str, ...]:
        counts = self.counts()
        keys = [
            key
            for key, _name in self._kinds
            if key not in IDLE_KINDS
            and (key not in self._hidden_from_results or counts.get(key, 0) > 0)
        ]
        return (OTHER_KEY, *keys)

    def extract_names(self) -> str:
        names = [
            name
            for key, name in self._kinds
            if key not in self._hidden_from_results and key not in IDLE_KINDS
        ]
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

    def add(self, image_path: Path, kind: str) -> None:
        self.add_many([image_path], kind)

    def add_many(self, image_paths: list[Path], kind: str) -> int:
        if kind not in self.classes():
            raise ValueError(kind)
        added = 0
        dest = bundle_dir()
        images_dir = dest / "images"
        used_by_kind: dict[str, set[str]] = {}
        by_path = {item["path"]: item for item in self._items}
        for image_path in image_paths:
            if not image_path.is_file():
                continue
            folder_name = kind_folder_name(kind)
            used = used_by_kind.setdefault(folder_name, image_names_in(images_dir / folder_name))
            relative = store_image(image_path, images_dir, used, kind)
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

    def items_of(self, kind: str) -> list[dict[str, str]]:
        return [item for item in self._items if item.get("kind") == kind]

    def _matches_path(self, stored: str, image_path: Path) -> bool:
        left = Path(stored)
        right = image_path
        if stored == str(image_path) or left == right:
            return True
        if left.name == right.name and left.parent.name == right.parent.name:
            return True
        try:
            return left.resolve() == right.resolve()
        except OSError:
            return False

    def set_kind(self, image_path: Path, kind: str) -> bool:
        if kind not in self.classes():
            raise ValueError(kind)
        changed = False
        for item in self._items:
            if self._matches_path(item["path"], image_path):
                item["kind"] = kind
                changed = True
        if changed:
            self._save_items()
        return changed

    def remove_at(self, kind: str, index: int) -> Path | None:
        matched = [(i, item) for i, item in enumerate(self._items) if item.get("kind") == kind]
        if index < 0 or index >= len(matched):
            return None
        item_index, item = matched[index]
        path = Path(item["path"])
        del self._items[item_index]
        self._save_items()
        self._unlink_if_ours(path)
        return path

    def remove(self, image_path: Path) -> bool:
        kept = []
        removed: Path | None = None
        for item in self._items:
            if removed is None and self._matches_path(item["path"], image_path):
                removed = Path(item["path"])
                continue
            kept.append(item)
        if removed is None:
            return False
        self._items = kept
        self._save_items()
        self._unlink_if_ours(removed)
        self._unlink_if_ours(image_path)
        return True

    def _unlink_if_ours(self, image_path: Path) -> None:
        try:
            root = bundle_dir() / "images"
            if image_path.is_file() and root in image_path.resolve().parents:
                image_path.unlink()
        except OSError:
            pass

    def missing_for_train(self) -> list[str]:
        counts = self.counts()
        return [
            f"{self.name_of(key)} {counts.get(key, 0)} 枚"
            for key in self.train_classes()
            if counts.get(key, 0) < MIN_SCENE_SAMPLES
        ]

    def can_train(self) -> bool:
        return bool(self._kinds) and not self.missing_for_train()
