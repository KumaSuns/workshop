from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.paths import IMAGE_EXTENSIONS, SKILLS_IMAGES_DIR, USE_TSUM_REGISTRY


def _load_registry() -> dict[str, str]:
    if not USE_TSUM_REGISTRY.is_file():
        return {}
    try:
        payload = json.loads(USE_TSUM_REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def skill_tsum_choices() -> list[tuple[str, str]]:
    registry = _load_registry()
    ids = set(registry.keys())
    if SKILLS_IMAGES_DIR.is_dir():
        for folder in SKILLS_IMAGES_DIR.iterdir():
            if folder.is_dir() and not folder.name.startswith("."):
                ids.add(folder.name)
    return sorted(((tid, registry.get(tid, tid)) for tid in ids), key=lambda row: row[1].casefold())


def registered_skills_by_sample() -> dict[str, str]:
    registry = _load_registry()
    found: dict[str, str] = {}
    if not SKILLS_IMAGES_DIR.is_dir():
        return found
    prefix = "skill_"
    for folder in SKILLS_IMAGES_DIR.iterdir():
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        display = registry.get(folder.name, folder.name)
        for path in folder.iterdir():
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            stem = path.stem
            if not stem.startswith(prefix):
                continue
            sample_id = stem[len(prefix) :]
            if sample_id:
                found[sample_id] = display
    return found


def save_skill_image(image_path: Path, tsum_id: str, sample_id: str) -> Path:
    if not image_path.is_file():
        raise ValueError("画像がありません")
    folder = SKILLS_IMAGES_DIR / tsum_id
    folder.mkdir(parents=True, exist_ok=True)
    suffix = image_path.suffix.lower() if image_path.suffix.lower() in IMAGE_EXTENSIONS else ".png"
    dest = folder / f"skill_{sample_id}{suffix}"
    if dest.exists():
        return dest
    shutil.copy2(image_path, dest)
    return dest
