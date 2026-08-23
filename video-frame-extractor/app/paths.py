from __future__ import annotations

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
WORKSHOP_ROOT = APP_ROOT.parent
TRAINER_IPC_NAME = "workshop-tsumtsum-screen-recognition"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
IPC_NAME = "workshop-video-frame-extractor"
_KIND_FOLDER_RE = re.compile(r"[^A-Za-z0-9._-]+")


def kind_folder_name(kind: str) -> str:
    name = _KIND_FOLDER_RE.sub("_", str(kind or "other").strip()).strip("._") or "other"
    if name in {".", ".."}:
        return "other"
    return name


def kind_dir(root: Path, kind: str) -> Path:
    return root / kind_folder_name(kind)
