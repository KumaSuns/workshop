from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from threading import Event

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from app.bluestacks import capture_window_frame
from app.paths import APP_ROOT

_FPS = 10
_DIR = APP_ROOT / "data" / "play_videos"


def play_video_path() -> Path:
    _DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _DIR / f"play_{stamp}.mp4"


class RecordWorker(QThread):
    failed = Signal(str)
    saved = Signal(str)

    def __init__(self, stop: Event, dest: Path, parent=None) -> None:
        super().__init__(parent)
        self._stop = stop
        self._dest = dest

    def run(self) -> None:
        writer = None
        size = (0, 0)
        try:
            while not self.isInterruptionRequested() and not self._stop.is_set():
                image = capture_window_frame()
                if image is None or image.isNull():
                    time.sleep(1 / _FPS)
                    continue
                frame = _qimage_bgr(image)
                if frame is None:
                    time.sleep(1 / _FPS)
                    continue
                height, width = frame.shape[:2]
                width -= width % 2
                height -= height % 2
                if width < 80 or height < 80:
                    time.sleep(1 / _FPS)
                    continue
                frame = frame[:height, :width]
                if writer is None:
                    size = (width, height)
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    writer = cv2.VideoWriter(str(self._dest), fourcc, _FPS, size)
                    if not writer.isOpened():
                        self.failed.emit("動画ファイルを開けませんでした")
                        return
                if (width, height) != size:
                    frame = cv2.resize(frame, size)
                writer.write(frame)
                time.sleep(1 / _FPS)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        finally:
            if writer is not None:
                writer.release()
        stopped = self.isInterruptionRequested() or self._stop.is_set()
        if not self._dest.is_file() or self._dest.stat().st_size < 1:
            if not stopped:
                self.failed.emit("動画を保存できませんでした")
            return
        self.saved.emit(str(self._dest))


def _qimage_bgr(image: QImage):
    converted = image.convertToFormat(QImage.Format.Format_RGB888)
    width = converted.width()
    height = converted.height()
    if width < 1 or height < 1:
        return None
    stride = converted.bytesPerLine()
    ptr = converted.constBits()
    size = converted.sizeInBytes()
    try:
        mv = memoryview(ptr)[:size]
    except TypeError:
        mv = bytes(ptr[:size])
    raw = np.frombuffer(mv, dtype=np.uint8)
    if stride == width * 3:
        rgb = raw.reshape((height, width, 3)).copy()
    else:
        rgb = raw.reshape((height, stride))[:, : width * 3].copy()
        rgb = rgb.reshape((height, width, 3))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
