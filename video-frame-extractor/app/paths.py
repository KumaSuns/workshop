from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
WORKSHOP_ROOT = APP_ROOT.parent
TRAINER_IPC_NAME = "workshop-tsumtsum-screen-recognition"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
IPC_NAME = "workshop-video-frame-extractor"
