from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
WORKSHOP_ROOT = APP_ROOT.parent
VIDEO_EXTRACTOR_MAIN = WORKSHOP_ROOT / "video-frame-extractor" / "main.py"
DATA_SYNC_PATH = WORKSHOP_ROOT / "video-frame-extractor" / "app" / "data_sync.py"
SERVER_SYNC_PATH = WORKSHOP_ROOT / "video-frame-extractor" / "app" / "server_sync.py"
SKILLS_IMAGES_DIR = WORKSHOP_ROOT / "video-frame-extractor" / "app" / "assets" / "images" / "skills"
USE_TSUM_MODELS = WORKSHOP_ROOT / "video-frame-extractor" / "app" / "assets" / "models" / "use_tsum"
USE_TSUM_REGISTRY = USE_TSUM_MODELS / "registry.json"
USE_TSUM_META = USE_TSUM_MODELS / "meta.json"
USE_TSUMS_IMAGES = WORKSHOP_ROOT / "video-frame-extractor" / "app" / "assets" / "images" / "use_tsums"
DATA_DIR = APP_ROOT / "data"
COIN_CROP_ROOT = WORKSHOP_ROOT / "data" / "coin_crops"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
IPC_NAME = "workshop-tsumtsum-screen-recognition"
EXTRACTOR_IPC_NAME = "workshop-video-frame-extractor"
