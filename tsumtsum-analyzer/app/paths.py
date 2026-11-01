from __future__ import annotations

import sys
from pathlib import Path


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _app_root() -> Path:
    if _frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _bundle_root() -> Path:
    if _frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return _app_root()
    return _app_root()


APP_ROOT = _app_root()
BUNDLE_ROOT = _bundle_root()
WORKSHOP_ROOT = APP_ROOT if _frozen() else APP_ROOT.parent
ANALYZE_ROOT = BUNDLE_ROOT if _frozen() else WORKSHOP_ROOT / "tsumtsum-analyze"
DATA_DIR = (BUNDLE_ROOT / "data") if _frozen() else (APP_ROOT / "data")
ASSETS_DIR = DATA_DIR / "assets"
OUTPUT_DIR = APP_ROOT / "output"
IPC_NAME = "workshop-tsumtsum-analyzer"
APP_NAME = "ツムツム解析"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv"}
EXE_DIST_DIR = APP_ROOT / "dist" / APP_NAME
EXE_PATH = EXE_DIST_DIR / f"{APP_NAME}.exe"
