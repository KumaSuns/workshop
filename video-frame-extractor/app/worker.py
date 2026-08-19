from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.extractor import SamplePoint, VideoInfo, extract_frames


class ExtractWorker(QThread):
    progress = Signal(int, int, str)
    finished_ok = Signal(list)
    failed = Signal(str)

    def __init__(self, info: VideoInfo, points: list[SamplePoint], output_dir: Path) -> None:
        super().__init__()
        self.info = info
        self.points = points
        self.output_dir = output_dir

    def run(self) -> None:
        try:
            paths = extract_frames(
                self.info,
                self.points,
                self.output_dir,
                progress=lambda current, total, name: self.progress.emit(current, total, name),
            )
            self.finished_ok.emit([str(path) for path in paths])
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
