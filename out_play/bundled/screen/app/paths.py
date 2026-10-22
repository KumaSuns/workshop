from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
WORKSHOP_ROOT = APP_ROOT.parent.parent
ASSETS = APP_ROOT.parent / "assets"
VIDEO_EXTRACTOR_MAIN = ASSETS / "main.py"
DATA_SYNC_PATH = ASSETS / "data_sync.py"
SERVER_SYNC_PATH = ASSETS / "server_sync.py"
SKILLS_IMAGES_DIR = ASSETS / "images" / "skills"
USE_TSUM_REGISTRY = ASSETS / "models" / "use_tsum" / "registry.json"
DATA_DIR = APP_ROOT / "data"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
IPC_NAME = "workshop-tsumtsum-screen-recognition"
EXTRACTOR_IPC_NAME = "workshop-video-frame-extractor"
