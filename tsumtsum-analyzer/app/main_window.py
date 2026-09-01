from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.paths import APP_NAME, APP_ROOT, OUTPUT_DIR, VIDEO_EXTENSIONS
from app.worker import AnalyzeWorker

RESULT_ROWS = (
    ("duration", "動画の長さ"),
    ("go_timeup", "GO → TIME UP"),
    ("fever", "FEVER"),
    ("skill", "スキル"),
            ("tsum", "使用ツム"),
            ("used_items", "使ったアイテム"),
            ("item_cost", "アイテム消費"),
    ("play_coin", "coin のコイン"),
    ("result_coin", "result のコイン"),
    ("play_net", "coin から引いた"),
    ("result_net", "result から引いた"),
    ("coin_ratio", "コイン倍率"),
    ("play_per_min", "coin のコイン効率"),
    ("result_per_min", "result のコイン効率"),
)

STYLESHEET = """
QMainWindow, QWidget { background: #f4f6fb; color: #1c2430; font-size: 14px; }
QPushButton {
    background: #ffffff;
    color: #1c2430;
    border: 1px solid #d0d7e2;
    border-radius: 10px;
    padding: 12px 18px;
    font-weight: 700;
}
QPushButton#primary { background: #3b6cff; color: #ffffff; border: none; }
QPushButton:disabled { background: #e8ecf2; color: #8b95a4; border: 1px solid #d0d7e2; }
QProgressBar {
    background: #e8ecf2;
    border: 1px solid #d0d7e2;
    border-radius: 8px;
    text-align: center;
    color: #1c2430;
    min-height: 22px;
}
QProgressBar::chunk { background: #3b6cff; border-radius: 8px; }
QLabel#title { font-size: 22px; font-weight: 700; color: #1c2430; }
QLabel#file { color: #5b6578; }
QTableWidget {
    background: #ffffff;
    alternate-background-color: #f8fafc;
    gridline-color: #e2e8f0;
    border: 1px solid #d7dee8;
    border-radius: 8px;
    color: #1c2430;
}
QTableWidget::item { padding: 6px 10px; }
QHeaderView::section {
    background: #eef2f7;
    color: #334155;
    border: none;
    border-right: 1px solid #d7dee8;
    border-bottom: 1px solid #d7dee8;
    padding: 8px 10px;
    font-weight: 700;
}
QTableCornerButton::section { background: #eef2f7; border: none; }
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ツムツム解析")
        self.resize(720, 760)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLESHEET)
        self._path: Path | None = None
        self.worker: AnalyzeWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        title = QLabel("ツムツム解析")
        title.setObjectName("title")
        layout.addWidget(title)
        self.file_label = QLabel("動画を開いてください")
        self.file_label.setObjectName("file")
        layout.addWidget(self.file_label)
        row = QHBoxLayout()
        self.open_btn = QPushButton("動画を開く")
        self.analyze_btn = QPushButton("解析")
        self.analyze_btn.setObjectName("primary")
        self.analyze_btn.setEnabled(False)
        row.addWidget(self.open_btn)
        row.addWidget(self.analyze_btn)
        layout.addLayout(row)
        self.shortcut_btn = QPushButton("起動アイコン作成")
        layout.addWidget(self.shortcut_btn)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.status = QLabel("")
        layout.addWidget(self.status)
        self.table = QTableWidget(len(RESULT_ROWS), 2)
        self.table.setHorizontalHeaderLabels(["項目", "値"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)
        self._fill_table(None)
        self.setCentralWidget(root)
        self.open_btn.clicked.connect(self.open_video)
        self.analyze_btn.clicked.connect(self.start_analyze)
        self.shortcut_btn.clicked.connect(self.create_launch_shortcut)

    def _set_path(self, path: Path) -> None:
        self._path = path
        self._remember_video_dir(path)
        self.file_label.setText(path.name)
        self.analyze_btn.setEnabled(self.worker is None)
        self._fill_table(None)
        self.status.setText("")

    def _last_video_dir(self) -> str:
        if self._path is not None and self._path.parent.is_dir():
            return str(self._path.parent.resolve())
        own = QSettings("workshop", "TsumTsum Analyzer")
        saved = str(own.value("last_video_dir", "") or "")
        if saved and Path(saved).is_dir():
            return saved
        workshop = QSettings("workshop", "VideoFrameExtractor")
        for key in ("last_dir/video", "last_video_dir"):
            saved = str(workshop.value(key, "") or "")
            if saved and Path(saved).is_dir():
                return saved
        return ""

    def _remember_video_dir(self, path: Path) -> None:
        folder = path if path.is_dir() else path.parent
        if folder.is_dir():
            QSettings("workshop", "TsumTsum Analyzer").setValue(
                "last_video_dir", str(folder.resolve())
            )

    def _fill_table(self, values: dict[str, str] | None) -> None:
        flags = Qt.ItemFlag.ItemIsEnabled
        for row, (key, caption) in enumerate(RESULT_ROWS):
            name = QTableWidgetItem(caption)
            name.setFlags(flags)
            value = QTableWidgetItem("—" if values is None else values.get(key, "—"))
            value.setFlags(flags)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, value)
        self.table.resizeRowsToContents()

    def open_video(self) -> None:
        if self.worker is not None:
            return
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "動画を開く",
            self._last_video_dir(),
            "動画 (*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.wmv)",
        )
        if not selected:
            return
        self._set_path(Path(selected))

    def start_analyze(self) -> None:
        if self._path is None or self.worker is not None:
            return
        dest = OUTPUT_DIR / self._path.stem
        dest.mkdir(parents=True, exist_ok=True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status.setText("解析中です")
        self.worker = AnalyzeWorker(self._path, dest)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()
        self.open_btn.setEnabled(False)
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText("解析中")

    def on_progress(self, current: int, total: int, name: str) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(current)
        self.status.setText(name)
        QApplication.processEvents()

    def on_finished(self, result) -> None:
        self.progress.setVisible(False)
        self.worker = None
        self.open_btn.setEnabled(True)
        self.analyze_btn.setEnabled(True)
        self.analyze_btn.setText("解析")
        self._fill_table(
            {
                "duration": result.duration,
                "go_timeup": result.go_timeup,
                "fever": result.fever_count,
                "skill": result.skill_count,
                "tsum": result.used_tsum,
                "used_items": result.used_items,
                "item_cost": result.item_cost,
                "play_coin": result.play_coin,
                "result_coin": result.result_coin,
                "play_net": result.play_net,
                "result_net": result.result_net,
                "coin_ratio": result.coin_ratio,
                "play_per_min": result.play_per_min,
                "result_per_min": result.result_per_min,
            }
        )
        self.status.setText("")

    def on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.worker = None
        self.open_btn.setEnabled(True)
        self.analyze_btn.setEnabled(self._path is not None)
        self.analyze_btn.setText("解析")
        self.status.setText("")
        if "中止" in message:
            QMessageBox.information(self, "解析を中止", "中止しました。")
            return
        QMessageBox.critical(self, "失敗しました", message)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        if self.worker is not None:
            return
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        videos = [path for path in paths if path.suffix.lower() in VIDEO_EXTENSIONS]
        if videos:
            self._set_path(videos[0])
            event.acceptProposedAction()

    def create_launch_shortcut(self) -> None:
        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        if not desktop:
            QMessageBox.warning(self, "デスクトップがありません", "デスクトップの場所が分かりませんでした。")
            return
        lnk = Path(desktop) / f"{APP_NAME}.lnk"
        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        target = pythonw if pythonw.exists() else python
        script = APP_ROOT / "main.py"
        icon = APP_ROOT / "app.ico"
        icon_path = icon if icon.is_file() else None

        def ps_quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        icon_line = f"$s.IconLocation = {ps_quote(str(icon_path) + ',0')}" if icon_path else ""
        command = (
            "$ws = New-Object -ComObject WScript.Shell\n"
            f"$s = $ws.CreateShortcut({ps_quote(str(lnk))})\n"
            f"$s.TargetPath = {ps_quote(str(target))}\n"
            f"$s.Arguments = {ps_quote(chr(34) + str(script) + chr(34))}\n"
            f"$s.WorkingDirectory = {ps_quote(str(APP_ROOT))}\n"
            "$s.WindowStyle = 1\n"
            f"$s.Description = {ps_quote(APP_NAME)}\n"
            f"{icon_line}\n"
            "$s.Save()\n"
        )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", command],
                check=False,
                capture_output=True,
                text=True,
                creationflags=flags,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "アイコンを作れませんでした", str(exc))
            return
        if result.returncode != 0 or not lnk.exists():
            err = (result.stderr or result.stdout or "ショートカットを作れませんでした").strip()
            QMessageBox.critical(self, "アイコンを作れませんでした", err)
            return
        QMessageBox.information(self, "起動アイコン", f"デスクトップに作りました。\n{lnk}")
