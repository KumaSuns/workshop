from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.extractor import SamplePoint, VideoInfo, extract_frames
from app.scene_scan import extract_scene_frames, find_scene_points


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


class SceneExtractWorker(QThread):
    progress = Signal(int, int, str)
    finished_ok = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        info: VideoInfo,
        output_dir: Path,
        points: list[SamplePoint] | None = None,
        want_kinds: set[str] | None = None,
        search_names: str = "画面",
    ) -> None:
        super().__init__()
        self.info = info
        self.output_dir = output_dir
        self.points = points
        self.want_kinds = want_kinds
        self.search_names = search_names
        self.found_points: list[SamplePoint] = list(points or [])

    def run(self) -> None:
        try:
            if self.points is not None:
                paths = extract_scene_frames(
                    self.info,
                    self.points,
                    self.output_dir,
                    progress=lambda current, total, name: self.progress.emit(current, total, name),
                )
                self.finished_ok.emit([str(path) for path in paths])
                return
            self.progress.emit(0, max(self.info.frame_count, 1), f"{self.search_names}を探しています")
            points = find_scene_points(
                self.info,
                progress=lambda current, total, name: self.progress.emit(current, total, name),
                want_kinds=self.want_kinds,
            )
            self.found_points = points
            self.finished_ok.emit([])
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
