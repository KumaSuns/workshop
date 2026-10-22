from __future__ import annotations

import shutil
from pathlib import Path

from tsumtsum_analyze.roots import WORKSHOP_ROOT, assets_dir, data_dir, extractor_root


def _copy_file(src: Path, dest: Path) -> bool:
    if not src.is_file():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return True


def _copy_tree(src: Path, dest: Path) -> int:
    if not src.is_dir():
        return 0
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for child in src.rglob("*"):
        if not child.is_file():
            continue
        rel = child.relative_to(src)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(child, target)
        count += 1
    return count


def publish_bundle(dest_data: Path, dest_assets: Path | None = None) -> dict[str, int]:
    dest_data = Path(dest_data)
    dest_assets = Path(dest_assets) if dest_assets is not None else dest_data / "assets"
    src_data = data_dir()
    src_assets = assets_dir()
    src_extract = extractor_root()
    counts = {"models": 0, "skills": 0, "scene": 0}

    bundle = dest_data / "extractor"
    bundle.mkdir(parents=True, exist_ok=True)
    scene_src = src_data / "extractor" / "scene.pt"
    if not scene_src.is_file():
        scene_src = src_extract / "scene.pt"
    labels_src = src_data / "extractor" / "scene_labels.json"
    if not labels_src.is_file():
        labels_src = src_extract / "scene_labels.json"
    if _copy_file(scene_src, bundle / "scene.pt"):
        counts["scene"] += 1
    if _copy_file(labels_src, bundle / "scene_labels.json"):
        counts["scene"] += 1

    for name in ("item_slots.json", "coin_box_patterns.json", "index.json"):
        _copy_file(src_data / name, dest_data / name)
    models = src_data / "models"
    if models.is_dir():
        counts["models"] = _copy_tree(models, dest_data / "models")

    counts["skills"] = _copy_tree(src_assets / "images" / "skills", dest_assets / "images" / "skills")
    _copy_tree(src_assets / "models" / "use_tsum", dest_assets / "models" / "use_tsum")
    return counts


def default_analyzer_dirs() -> tuple[Path, Path]:
    app = WORKSHOP_ROOT / "tsumtsum-analyzer"
    data = app / "data"
    return data, data / "assets"
