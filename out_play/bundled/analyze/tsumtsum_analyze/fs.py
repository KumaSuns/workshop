from __future__ import annotations

import re
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_KIND_FOLDER_RE = re.compile(r"[^A-Za-z0-9._-]+")


def kind_folder_name(kind: str) -> str:
    name = _KIND_FOLDER_RE.sub("_", str(kind or "other").strip()).strip("._") or "other"
    if name in {".", ".."}:
        return "other"
    return name


def kind_dir(root: Path, kind: str) -> Path:
    return root / kind_folder_name(kind)
