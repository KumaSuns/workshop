from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from tsumtsum_analyze.pipeline import AnalysisResult, analyze_video


class AnalyzeWorker(QThread):
    progress = Signal(int, int, str)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, path: Path, output_dir: Path) -> None:
        super().__init__()
        self.path = path
        self.output_dir = output_dir

    def run(self) -> None:
        try:
            result = analyze_video(
                self.path,
                self.output_dir,
                progress=lambda current, total, name: self.progress.emit(current, total, name),
                should_stop=self.isInterruptionRequested,
            )
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
