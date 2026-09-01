from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
WORKSHOP_ROOT = APP_ROOT.parent
ANALYZE_ROOT = WORKSHOP_ROOT / "tsumtsum-analyze"
DATA_DIR = APP_ROOT / "data"
ASSETS_DIR = DATA_DIR / "assets"
OUTPUT_DIR = APP_ROOT / "output"
IPC_NAME = "workshop-tsumtsum-analyzer"
APP_NAME = "ツムツム解析"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv"}
