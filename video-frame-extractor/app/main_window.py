from __future__ import annotations

from pathlib import Path

import cv2
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QImage, QPixmap, QShortcut, QKeySequence, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.extractor import (
    RANGE_END,
    RANGE_START,
    VIDEO_EXTENSIONS,
    VideoInfo,
    format_timecode,
    grab_frame,
    read_video_info,
    sample_points,
    extracted_file_for,
    write_image,
)
from app.worker import ExtractWorker
from app.handoff import send_images_to_tsumtsum

STYLESHEET = """
QMainWindow, QWidget {
    background: #16181d;
    color: #e8eaed;
    font-family: "Yu Gothic UI", "Segoe UI", sans-serif;
    font-size: 13px;
}
QLabel#title { font-size: 18px; font-weight: 700; }
QLabel#hint { color: #9aa3b2; }
QPushButton {
    background: #2a303b;
    color: #e8eaed;
    border: none;
    padding: 8px 14px;
    border-radius: 8px;
}
QPushButton:hover { background: #3a4250; }
QPushButton:disabled { color: #6b7380; background: #22262e; }
QPushButton#primary { background: #5b6cff; font-weight: 600; }
QPushButton#primary:hover { background: #6e7dff; }
QListWidget {
    background: #101216;
    border: 1px solid #2a303b;
    border-radius: 10px;
    padding: 6px;
    outline: none;
}
QListWidget::item { padding: 7px 10px; border-radius: 6px; }
QListWidget::item:selected { background: #2c3344; }
QFrame#panel {
    background: #1c2028;
    border: 1px solid #2a303b;
    border-radius: 12px;
}
QSpinBox {
    background: #101216;
    color: #e8eaed;
    border: 1px solid #2a303b;
    border-radius: 6px;
    padding: 6px 10px;
    min-width: 80px;
}
QProgressBar {
    background: #101216;
    border: 1px solid #2a303b;
    border-radius: 6px;
    text-align: center;
    color: #e8eaed;
}
QProgressBar::chunk { background: #5b6cff; border-radius: 6px; }
QLabel#preview {
    background: #101216;
    border: 1px solid #2a303b;
    border-radius: 10px;
}
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("動画フレーム抜き出し")
        self.resize(1100, 760)
        self.setMinimumSize(860, 600)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLESHEET)

        self.info: VideoInfo | None = None
        self.worker: ExtractWorker | None = None
        self._settings = QSettings("workshop", "VideoFrameExtractor")
        self.output_dir = Path(__file__).resolve().parent.parent / "output"
        saved_out = str(self._settings.value("last_output_dir", "") or "")
        if saved_out and Path(saved_out).is_dir():
            self.output_dir = Path(saved_out)
        self._cap = None
        self._full_pixmap: QPixmap | None = None
        self._saved_by_index: dict[int, Path] = {}
        self._preview_point = None

        self._build_ui()
        QShortcut(QKeySequence.StandardKey.Open, self, self.open_video)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        top = QFrame()
        top.setObjectName("panel")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(16, 12, 16, 12)
        title_box = QVBoxLayout()
        title = QLabel("動画フレーム抜き出し")
        title.setObjectName("title")
        self.hint_label = QLabel(
            f"動画をドロップまたは「動画を開く」。再生時間の {int(RANGE_START*100)}%〜{int(RANGE_END*100)}% から、指定枚数を等間隔で画像にします。"
            "1枚のときは再生時間の中心（50%）です。"
        )
        self.hint_label.setObjectName("hint")
        self.hint_label.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(self.hint_label)
        top_layout.addLayout(title_box, 1)
        self.open_btn = QPushButton("動画を開く")
        self.folder_btn = QPushButton("保存先")
        self.extract_btn = QPushButton("画像に抜き出す")
        self.extract_btn.setObjectName("primary")
        top_layout.addWidget(self.open_btn, 0, Qt.AlignmentFlag.AlignTop)
        top_layout.addWidget(self.folder_btn, 0, Qt.AlignmentFlag.AlignTop)
        top_layout.addWidget(self.extract_btn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(top)

        body = QSplitter(Qt.Orientation.Horizontal)
        left = QFrame()
        left.setObjectName("panel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        self.info_label = QLabel("まだ動画がありません")
        self.info_label.setObjectName("hint")
        self.info_label.setWordWrap(True)
        left_layout.addWidget(self.info_label)

        count_row = QHBoxLayout()
        count_row.addWidget(QLabel("抜き出す枚数"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 300)
        self.count_spin.setValue(10)
        count_row.addWidget(self.count_spin)
        count_row.addStretch(1)
        left_layout.addLayout(count_row)

        self.folder_label = QLabel(f"保存先: {self.output_dir}")
        self.folder_label.setObjectName("hint")
        self.folder_label.setWordWrap(True)
        left_layout.addWidget(self.folder_label)

        left_layout.addWidget(QLabel("抜き出し位置（クリックでプレビュー）"))
        self.point_list = QListWidget()
        left_layout.addWidget(self.point_list, 1)
        self.send_one_btn = QPushButton("この画像をツムツムに渡す")
        self.send_all_btn = QPushButton("すべてツムツムに渡す")
        left_layout.addWidget(self.send_one_btn)
        left_layout.addWidget(self.send_all_btn)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        left_layout.addWidget(self.progress)
        left.setMinimumWidth(300)

        right = QFrame()
        right.setObjectName("panel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        self.preview_title = QLabel("プレビュー")
        right_layout.addWidget(self.preview_title)
        self.preview = QLabel("動画を取り込むと、一覧をクリックして画像を確認できます")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(420, 280)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_layout.addWidget(self.preview, 1)

        body.addWidget(left)
        body.addWidget(right)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes([360, 740])
        layout.addWidget(body, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("準備完了")

        self.open_btn.clicked.connect(self.open_video)
        self.folder_btn.clicked.connect(self.choose_folder)
        self.extract_btn.clicked.connect(self.start_extract)
        self.count_spin.valueChanged.connect(self.refresh_points)
        self.point_list.currentItemChanged.connect(self.on_point_selected)
        self.send_one_btn.clicked.connect(self.send_current_to_tsumtsum)
        self.send_all_btn.clicked.connect(self.send_all_to_tsumtsum)
        self._update_buttons()

    def _update_buttons(self) -> None:
        busy = self.worker is not None
        ready = self.info is not None and not busy
        self.extract_btn.setEnabled(ready)
        self.open_btn.setEnabled(not busy)
        self.count_spin.setEnabled(not busy)
        self.send_one_btn.setEnabled(ready and self.point_list.currentItem() is not None)
        self.send_all_btn.setEnabled(ready and self.point_list.count() > 0)

    def _last_video_dir(self) -> str:
        saved = str(self._settings.value("last_video_dir", "") or "")
        if saved and Path(saved).is_dir():
            return saved
        return str(Path.home())

    def open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "動画を開く",
            self._last_video_dir(),
            "Video (*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.wmv)",
        )
        if path:
            self.load_video(Path(path))

    def choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "保存先フォルダ", str(self.output_dir))
        if path:
            self.output_dir = Path(path)
            self._settings.setValue("last_output_dir", str(self.output_dir))
            self.folder_label.setText(f"保存先: {self.output_dir}")

    def load_video(self, path: Path) -> None:
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            QMessageBox.warning(self, "未対応の形式", f"{path.suffix} には対応していません。")
            return
        try:
            self.info = read_video_info(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "読み込みに失敗", str(exc))
            return
        self._release_cap()
        self._saved_by_index = {}
        self.info_label.setText(
            f"{path.name}\n"
            f"{self.info.width} × {self.info.height}  /  {self.info.fps:.2f} fps\n"
            f"再生時間 {self.info.format_duration()}  /  {self.info.frame_count} フレーム\n"
            f"抜き出し範囲 {int(RANGE_START*100)}%〜{int(RANGE_END*100)}%"
        )
        self.refresh_points()
        self._update_buttons()
        self._settings.setValue("last_video_dir", str(path.parent.resolve()))
        self._settings.setValue("last_video_path", str(path.resolve()))
        self.statusBar().showMessage(f"{path.name} を読み込みました", 4000)

    def refresh_points(self) -> None:
        self.point_list.blockSignals(True)
        self.point_list.clear()
        if self.info is None:
            self.point_list.blockSignals(False)
            return
        points = sample_points(self.info, self.count_spin.value())
        for point in points:
            item = QListWidgetItem(
                f"{point.index:3d}  {format_timecode(point.seconds)}  ({point.percent * 100:.1f}%)"
            )
            item.setData(Qt.ItemDataRole.UserRole, point)
            self.point_list.addItem(item)
        self.point_list.blockSignals(False)
        self._relink_extracted_files()
        if self.point_list.count():
            self.point_list.setCurrentRow(0)

    def _relink_extracted_files(self) -> None:
        found: dict[int, Path] = {}
        if self.info is not None:
            for index in range(1, self.count_spin.value() + 1):
                match = extracted_file_for(self.output_dir, self.info.path.stem, index)
                if match is not None:
                    found[index] = match
        self._saved_by_index = found

    def on_point_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        point = current.data(Qt.ItemDataRole.UserRole)
        if point is None:
            return
        self.show_point(point)
        self._update_buttons()

    def show_point(self, point) -> None:
        saved = self._saved_by_index.get(point.index)
        pixmap = None
        source = "動画"
        if saved is not None and saved.exists():
            pixmap = QPixmap(str(saved))
            source = "保存済み"
        if pixmap is None or pixmap.isNull():
            frame = self._read_frame(point.frame)
            if frame is None:
                self.preview.setText("この位置の画像を取得できませんでした")
                self.preview_title.setText("プレビュー")
                return
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channels = rgb.shape
            image = QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(image)
        self._full_pixmap = pixmap
        self._preview_point = point
        self.preview_title.setText(
            f"プレビュー  {point.index} / {format_timecode(point.seconds)}  ({point.percent * 100:.1f}%)  {source}"
        )
        self._fit_preview()
        self.statusBar().showMessage(
            f"{point.index}枚目  {format_timecode(point.seconds)}  ({point.percent * 100:.1f}%)",
            3000,
        )

    def _read_frame(self, frame_index: int):
        if self.info is None:
            return None
        image = None
        if self._cap is not None and self._cap.isOpened():
            image = grab_frame(self._cap, frame_index, self.info.fps)
        if image is None:
            self._release_cap()
            self._cap = cv2.VideoCapture(str(self.info.path))
            if self._cap.isOpened():
                image = grab_frame(self._cap, frame_index, self.info.fps)
        return image

    def _fit_preview(self) -> None:
        if self._full_pixmap is None or self._full_pixmap.isNull():
            return
        self.preview.setPixmap(
            self._full_pixmap.scaled(
                self.preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _release_cap(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._full_pixmap is not None and not self._full_pixmap.isNull():
            self._fit_preview()

    def _point_image_path(self, point) -> Path:
        saved = self._saved_by_index.get(point.index)
        if saved is None and self.info is not None:
            saved = extracted_file_for(self.output_dir, self.info.path.stem, point.index)
            if saved is not None:
                self._saved_by_index[point.index] = saved
        if saved is not None and saved.exists():
            return saved
        if self.info is None:
            raise ValueError("動画がありません")
        dest = self.output_dir / f"{self.info.path.stem}_{point.index:03d}_{int(point.percent * 100):02d}pct.png"
        if (
            self._preview_point is not None
            and self._preview_point.index == point.index
            and self._full_pixmap is not None
            and not self._full_pixmap.isNull()
        ):
            if self._full_pixmap.save(str(dest), "PNG"):
                return dest
        frame = self._read_frame(point.frame)
        if frame is None:
            raise ValueError(f"{point.index}枚目の画像を取得できませんでした")
        write_image(dest, frame)
        return dest

    def _list_points(self) -> list:
        points = []
        for row in range(self.point_list.count()):
            item = self.point_list.item(row)
            point = item.data(Qt.ItemDataRole.UserRole)
            if point is not None:
                points.append(point)
        return points

    def send_current_to_tsumtsum(self) -> None:
        item = self.point_list.currentItem()
        if item is None:
            return
        point = item.data(Qt.ItemDataRole.UserRole)
        if point is None:
            return
        self._handoff_points([point])

    def send_all_to_tsumtsum(self) -> None:
        points = self._list_points()
        if not points:
            QMessageBox.information(self, "画像がありません", "先に動画を開いてください。")
            return
        self._handoff_points(points)

    def _handoff_points(self, points: list) -> None:
        try:
            paths = [self._point_image_path(point) for point in points]
            result = send_images_to_tsumtsum(paths)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "渡せませんでした", str(exc))
            return
        count = len(paths)
        if result == "sent":
            message = f"{count} 枚をツムツムアプリに渡しました。そちらで四角を囲んで「この範囲を保存」してください。"
        else:
            message = f"ツムツムアプリを開いて {count} 枚を取り込みました。四角を囲んで「この範囲を保存」してください。"
        self.statusBar().showMessage(message, 6000)
        QMessageBox.information(self, "渡しました", message)

    def start_extract(self) -> None:
        if self.info is None or self.worker is not None:
            return
        points = sample_points(self.info, self.count_spin.value())
        self.progress.setVisible(True)
        self.progress.setRange(0, len(points))
        self.progress.setValue(0)
        self.worker = ExtractWorker(self.info, points, self.output_dir)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()
        self._update_buttons()
        self.statusBar().showMessage("抜き出し中です…")

    def on_progress(self, current: int, total: int, name: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.statusBar().showMessage(f"{current}/{total}  {name}")

    def on_finished(self, paths: list[str]) -> None:
        self.worker = None
        self.progress.setVisible(False)
        self._update_buttons()
        self._saved_by_index = {
            index + 1: Path(path) for index, path in enumerate(paths)
        }
        if self.point_list.currentItem() is not None:
            self.on_point_selected(self.point_list.currentItem(), None)
        folder = self.output_dir
        self.statusBar().showMessage(f"{len(paths)} 枚を保存しました", 5000)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("抜き出し完了")
        box.setText(f"{len(paths)} 枚の画像を保存しました。\n{folder}")
        open_btn = box.addButton("フォルダを開く", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("OK", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            self._open_folder(folder)

    def on_failed(self, message: str) -> None:
        self.worker = None
        self.progress.setVisible(False)
        self._update_buttons()
        QMessageBox.critical(self, "抜き出しに失敗", message)

    def _open_folder(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in VIDEO_EXTENSIONS:
                self.load_video(path)
                event.acceptProposedAction()
                return
        event.ignore()

    def closeEvent(self, event) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(1000)
        self._release_cap()
        event.accept()
