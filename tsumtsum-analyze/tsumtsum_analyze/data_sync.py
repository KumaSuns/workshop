from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from tsumtsum_analyze.roots import data_dir as configured_data_dir, extractor_root

EXTRACTOR_ROOT = extractor_root()
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_KIND_FOLDER_RE = re.compile(r"[^A-Za-z0-9._-]+")


def kind_folder_name(kind: str) -> str:
    name = _KIND_FOLDER_RE.sub("_", str(kind or "other").strip()).strip("._") or "other"
    if name in {".", ".."}:
        return "other"
    return name
BUNDLE_NAME = "extractor"
OLD_LABELS_NAME = "scene_labels.json"
OLD_MODEL_NAME = "scene.pt"


def trainer_data_dir() -> Path:
    return configured_data_dir()


def bundle_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or trainer_data_dir()) / BUNDLE_NAME


def old_labels_path() -> Path:
    return EXTRACTOR_ROOT / OLD_LABELS_NAME


def old_model_path() -> Path:
    return EXTRACTOR_ROOT / OLD_MODEL_NAME


def labels_file(data_dir: Path | None = None) -> Path:
    bundled = bundle_dir(data_dir) / OLD_LABELS_NAME
    if bundled.is_file():
        return bundled
    return old_labels_path()


def model_file(data_dir: Path | None = None) -> Path:
    bundled = bundle_dir(data_dir) / OLD_MODEL_NAME
    if bundled.is_file():
        return bundled
    return old_model_path()


def resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def is_same_or_inside(path: Path, root: Path) -> bool:
    target = resolved(path)
    base = resolved(root)
    return target == base or base in target.parents


def looks_like_data_dir(path: Path) -> bool:
    if (path / "index.json").is_file():
        return True
    if (path / BUNDLE_NAME / OLD_LABELS_NAME).is_file():
        return True
    images = path / "images"
    if images.is_dir() and any(
        child.is_file() and child.suffix.lower() in IMAGE_EXTENSIONS for child in images.rglob("*")
    ):
        return True
    models = path / "models"
    if models.is_dir() and any(child.is_file() and child.suffix.lower() == ".pt" for child in models.iterdir()):
        return True
    return False


def resolve_data_dir(path: Path) -> Path | None:
    if looks_like_data_dir(path):
        return path
    inner = path / "data"
    if looks_like_data_dir(inner):
        return inner
    return None


def has_scene_bundle(path: Path) -> bool:
    return (path / BUNDLE_NAME / OLD_LABELS_NAME).is_file()


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_scene_payload(data_dir: Path | None = None) -> dict:
    return _read_json(labels_file(data_dir))


def resolve_sample_path(raw: str, root: Path | None = None) -> Path | None:
    path = Path(raw)
    if not path.is_absolute():
        path = (root or bundle_dir()) / path
    if path.is_file():
        return resolved(path)
    return None


def _unique_name(src: Path, used: set[str]) -> str:
    suffix = src.suffix.lower() if src.suffix else ".png"
    base = src.name
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in base)
    if not safe.lower().endswith(suffix):
        safe = f"{safe}{suffix}"
    if safe not in used:
        return safe
    digest = hashlib.sha1(str(resolved(src)).encode("utf-8")).hexdigest()[:8]
    return f"{Path(safe).stem}_{digest}{suffix}"


def image_names_in(folder: Path) -> set[str]:
    if not folder.is_dir():
        return set()
    return {child.name for child in folder.iterdir() if child.is_file()}


def store_image(src: Path, images_dir: Path, used: set[str] | None = None, kind: str = "other") -> str | None:
    if not src.is_file():
        return None
    folder_name = kind_folder_name(kind)
    dest_dir = images_dir / folder_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    names = used if used is not None else image_names_in(dest_dir)
    src_resolved = resolved(src)
    dest_resolved = resolved(dest_dir)
    try:
        if src_resolved.parent == dest_resolved:
            names.add(src.name)
            return f"images/{folder_name}/{src.name}"
    except OSError:
        pass
    name = src.name if src.name not in names else _unique_name(src, names)
    dest = dest_dir / name
    if src_resolved != resolved(dest):
        if is_same_or_inside(src_resolved, images_dir):
            shutil.move(str(src_resolved), str(dest))
        else:
            shutil.copy2(src, dest)
    names.add(name)
    return f"images/{folder_name}/{name}"


def pack_scene_into(dest: Path, data_dir: Path | None = None) -> dict[str, int]:
    root = dest
    images_dir = root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    payload = read_scene_payload(data_dir)
    kinds = payload.get("kinds") or []
    samples = payload.get("samples") or []
    used_by_kind: dict[str, set[str]] = {}
    packed = []
    missing = 0
    source_root = labels_file(data_dir).parent
    for item in samples:
        kind = str(item.get("kind") or "other")
        src = resolve_sample_path(str(item.get("path") or ""), source_root)
        if src is None:
            missing += 1
            continue
        folder_name = kind_folder_name(kind)
        used = used_by_kind.setdefault(folder_name, image_names_in(images_dir / folder_name))
        relative = store_image(src, images_dir, used, kind)
        if relative is None:
            missing += 1
            continue
        packed.append({"path": relative, "kind": kind})
    (root / OLD_LABELS_NAME).write_text(
        json.dumps({"kinds": kinds, "samples": packed}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    model_src = model_file(data_dir)
    if model_src.is_file():
        model_dest = root / OLD_MODEL_NAME
        if resolved(model_src) != resolved(model_dest):
            shutil.copy2(model_src, model_dest)
    return {"images": len(packed), "missing": missing, "model": int(model_src.is_file())}


def ensure_scene_packed(data_dir: Path | None = None) -> dict[str, int]:
    dest = bundle_dir(data_dir)
    dest.mkdir(parents=True, exist_ok=True)
    return pack_scene_into(dest, data_dir)


def copy_data_folder(data_dir: Path, dest_parent: Path) -> Path:
    dest = dest_parent / data_dir.name
    tmp = dest_parent / "_data_copying"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(data_dir, tmp)
    if dest.exists():
        shutil.rmtree(dest)
    tmp.rename(dest)
    if tmp.exists() and dest.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    return dest


def import_data_folder(data_dir: Path, source: Path) -> None:
    incoming = data_dir.parent / "_data_importing"
    outgoing = data_dir.parent / "_data_replacing"
    keep_scene = not has_scene_bundle(source) and has_scene_bundle(data_dir)
    if incoming.exists():
        shutil.rmtree(incoming)
    if outgoing.exists():
        shutil.rmtree(outgoing)
    shutil.copytree(source, incoming)
    if keep_scene:
        extra = incoming / BUNDLE_NAME
        if extra.exists():
            shutil.rmtree(extra)
        shutil.copytree(data_dir / BUNDLE_NAME, extra)
    imported = False
    try:
        if data_dir.exists():
            data_dir.rename(outgoing)
        incoming.rename(data_dir)
        imported = True
        if outgoing.exists():
            shutil.rmtree(outgoing)
    except Exception:
        if not data_dir.exists() and outgoing.exists():
            try:
                outgoing.rename(data_dir)
            except OSError:
                pass
        raise
    finally:
        if incoming.exists():
            shutil.rmtree(incoming, ignore_errors=True)
        if imported and outgoing.exists():
            shutil.rmtree(outgoing, ignore_errors=True)
