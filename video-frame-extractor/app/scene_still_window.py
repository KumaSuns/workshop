from __future__ import annotations

from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap, QCloseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.extractor import VideoInfo, format_timecode, grab_frame, write_image
from app.paths import kind_dir
from app.scene_labels import OTHER_KEY


class SceneStillWindow(QMainWindow):
    def __init__(self, host: QMainWindow) -> None:
        super().__init__(host)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("CAPTURE")
        self.resize(960, 720)
        self.setMinimumSize(640, 480)

        self._host = host
        self.info: VideoInfo | None = None
        self.output_dir = Path(".")
        self._cap = None
        self._full_pixmap: QPixmap | None = None
        self._frame = 0
        self._syncing = False
        self._saving = False
        self._saved_at: dict[int, list[tuple[str, str]]] = {}
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(80)
        self._play_timer.timeout.connect(self._play_step)

        self._build_ui()

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
        title = QLabel("CAPTURE")
        title.setObjectName("title")
        hint = QLabel(
            "「動画を開く」か、すでに開いている動画から、見たいシーンまで動かします。"
            "種類を選んで「この画面を画像にする」を押します。"
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(hint)
        top_layout.addLayout(title_box, 1)
        self.open_btn = QPushButton("動画を開く")
        top_layout.addWidget(self.open_btn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(top)

        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 12, 12, 12)
        self.preview_title = QLabel("プレビュー")
        panel_layout.addWidget(self.preview_title)
        self.preview = QLabel("動画を開くと、ここでシーンを選べます")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(480, 320)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        panel_layout.addWidget(self.preview, 1)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._on_slider)
        panel_layout.addWidget(self.slider)

        skip_label = QLabel("コマ送り")
        skip_label.setObjectName("hint")
        panel_layout.addWidget(skip_label)
        skip_row = QHBoxLayout()
        skip_row.setSpacing(8)
        self.back10_btn = QPushButton("10秒戻る")
        self.back5_btn = QPushButton("5秒戻る")
        self.back_btn = QPushButton("1秒戻る")
        self.fwd_btn = QPushButton("1秒進む")
        self.fwd5_btn = QPushButton("5秒進む")
        self.fwd10_btn = QPushButton("10秒進む")
        for button in (
            self.back10_btn,
            self.back5_btn,
            self.back_btn,
            self.fwd_btn,
            self.fwd5_btn,
            self.fwd10_btn,
        ):
            button.setMinimumHeight(40)
            skip_row.addWidget(button, 1)
        panel_layout.addLayout(skip_row)

        play_row = QHBoxLayout()
        self.play_btn = QPushButton("再生")
        self.play_btn.setMinimumHeight(40)
        self.time_label = QLabel("—")
        self.time_label.setObjectName("hint")
        play_row.addWidget(self.play_btn)
        play_row.addStretch(1)
        play_row.addWidget(self.time_label)
        panel_layout.addLayout(play_row)

        kind_row = QHBoxLayout()
        kind_row.addWidget(QLabel("種類"))
        self.kind_combo = QComboBox()
        kind_row.addWidget(self.kind_combo, 1)
        panel_layout.addLayout(kind_row)

        self.save_btn = QPushButton("この画面を画像にする")
        self.save_btn.setObjectName("primary")
        self.save_btn.setEnabled(False)
        panel_layout.addWidget(self.save_btn)
        self.save_status = QLabel("この位置は、まだ画像にしていません")
        self.save_status.setObjectName("hint")
        self.save_status.setWordWrap(True)
        panel_layout.addWidget(self.save_status)
        self.save_progress = QProgressBar()
        self.save_progress.setRange(0, 0)
        self.save_progress.setTextVisible(False)
        self.save_progress.setVisible(False)
        panel_layout.addWidget(self.save_progress)
        layout.addWidget(panel, 1)

        self.setCentralWidget(root)
        self.back10_btn.clicked.connect(lambda: self._nudge(-10))
        self.back5_btn.clicked.connect(lambda: self._nudge(-5))
        self.back_btn.clicked.connect(lambda: self._nudge(-1))
        self.fwd_btn.clicked.connect(lambda: self._nudge(1))
        self.fwd5_btn.clicked.connect(lambda: self._nudge(5))
        self.fwd10_btn.clicked.connect(lambda: self._nudge(10))
        self.play_btn.clicked.connect(self.toggle_play)
        self.save_btn.clicked.connect(self.save_current)
        self.kind_combo.currentIndexChanged.connect(self._refresh_save_status)
        self.open_btn.clicked.connect(self.open_video)
        for button in (
            self.back10_btn,
            self.back5_btn,
            self.back_btn,
            self.play_btn,
            self.fwd_btn,
            self.fwd5_btn,
            self.fwd10_btn,
            self.save_btn,
        ):
            button.setEnabled(False)
        self._fill_kind_combo()
        self.statusBar().showMessage("開いている動画から、見たいシーンを画像にします")

    def open_video(self) -> None:
        start = ""
        if hasattr(self._host, "_dialog_dir"):
            start = str(self._host._dialog_dir("video"))
        path, _ = QFileDialog.getOpenFileName(
            self,
            "動画を開く",
            start,
            "Video (*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.wmv)",
        )
        if not path:
            return
        remember = getattr(self._host, "_remember_dialog_dir", None)
        if callable(remember):
            remember("video", path)
        loader = getattr(self._host, "load_video", None)
        if callable(loader):
            loader(Path(path))
            return
        from app.extractor import read_video_info

        self.set_video(read_video_info(Path(path)), self.output_dir)

    def set_video(self, info: VideoInfo, output_dir: Path, start_frame: int | None = None) -> None:
        self._stop_play()
        self._release_cap()
        self.info = info
        self.output_dir = output_dir
        last = max(info.frame_count - 1, 0)
        self._syncing = True
        self.slider.setRange(0, last)
        frame = 0 if start_frame is None else max(0, min(int(start_frame), last))
        self.slider.setValue(frame)
        self._syncing = False
        self.slider.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.back10_btn.setEnabled(True)
        self.back5_btn.setEnabled(True)
        self.back_btn.setEnabled(True)
        self.fwd_btn.setEnabled(True)
        self.fwd5_btn.setEnabled(True)
        self.fwd10_btn.setEnabled(True)
        self.play_btn.setEnabled(True)
        self._saved_at.clear()
        self._fill_kind_combo()
        self._show_frame(frame)
        self.statusBar().showMessage(f"{info.path.name}  /  {info.format_duration()}", 5000)

    def _on_slider(self, value: int) -> None:
        if self._syncing:
            return
        self._stop_play()
        self._show_frame(value)

    def _nudge(self, seconds: float) -> None:
        if self.info is None:
            return
        self._stop_play()
        delta = int(round(seconds * self.info.fps))
        self._seek(self._frame + (delta if delta else int(seconds)))

    def toggle_play(self) -> None:
        if self.info is None:
            return
        if self._play_timer.isActive():
            self._stop_play()
            return
        last = max(self.info.frame_count - 1, 0)
        if self._frame >= last:
            self._seek(0)
        self._play_timer.start()
        self.play_btn.setText("停止")

    def _play_step(self) -> None:
        if self.info is None:
            self._stop_play()
            return
        step = max(1, int(round(self.info.fps * self._play_timer.interval() / 1000.0)))
        nxt = self._frame + step
        last = max(self.info.frame_count - 1, 0)
        if nxt >= last:
            self._seek(last)
            self._stop_play()
            return
        self._seek(nxt)

    def _stop_play(self) -> None:
        self._play_timer.stop()
        self.play_btn.setText("再生")

    def _seek(self, frame: int) -> None:
        if self.info is None:
            return
        last = max(self.info.frame_count - 1, 0)
        frame = max(0, min(int(frame), last))
        self._syncing = True
        self.slider.setValue(frame)
        self._syncing = False
        self._show_frame(frame)

    def _show_frame(self, frame: int) -> None:
        if self.info is None:
            return
        image = self._read_frame(frame)
        if image is None:
            self.preview.setText("この位置の画像を取得できませんでした")
            return
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        qimage = QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888).copy()
        self._full_pixmap = QPixmap.fromImage(qimage)
        self._frame = frame
        seconds = frame / self.info.fps
        self.preview_title.setText(f"プレビュー  {format_timecode(seconds)}")
        self.time_label.setText(f"{format_timecode(seconds)}  /  {self.info.format_duration()}")
        self._fit_preview()
        self._refresh_save_status()

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

    def _fill_kind_combo(self) -> None:
        labels = getattr(self._host, "scene_labels", None)
        current = self.kind_combo.currentData()
        self.kind_combo.blockSignals(True)
        self.kind_combo.clear()
        if labels is None:
            self.kind_combo.blockSignals(False)
            return
        self.kind_combo.addItem(labels.name_of(OTHER_KEY), OTHER_KEY)
        for key, name in labels.kinds():
            self.kind_combo.addItem(name, key)
        if current:
            index = self.kind_combo.findData(current)
            if index >= 0:
                self.kind_combo.setCurrentIndex(index)
        self.kind_combo.blockSignals(False)

    def _selected_kind(self) -> tuple[str, str] | None:
        key = self.kind_combo.currentData()
        if not key:
            return None
        name = self.kind_combo.currentText().strip() or str(key)
        return str(key), name

    def _captures_for_frame(self, frame: int) -> list[tuple[str, str]]:
        hits = list(self._saved_at.get(frame, []))
        seen = {file_name for _name, file_name in hits}
        if self.info is None:
            return hits
        stamp = format_timecode(frame / self.info.fps).replace(":", "-")
        stem = self.info.path.stem
        prefix = f"{stem}_{stamp}"
        labels = getattr(self._host, "scene_labels", None)
        kinds: list[tuple[str, str]] = []
        if labels is not None:
            kinds.append((OTHER_KEY, labels.name_of(OTHER_KEY)))
            kinds.extend(labels.kinds())
        else:
            kinds.append(("scene", "scene"))
        for key, name in kinds:
            folder = kind_dir(self.output_dir, key)
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob(f"{prefix}*.png")):
                if path.name in seen:
                    continue
                hits.append((name, path.name))
                seen.add(path.name)
        return hits

    def _refresh_save_status(self) -> None:
        if self._saving:
            return
        if self.info is None:
            self.save_status.setText("動画を開くと、ここで保存済みかどうかが分かります")
            self.save_status.setObjectName("hint")
            self.save_btn.setText("この画面を画像にする")
            self._restyle(self.save_status)
            return
        hits = self._captures_for_frame(self._frame)
        if hits:
            parts = "  /  ".join(f"{name}  {file_name}" for name, file_name in hits)
            self.save_status.setText(f"この位置は保存済みです\n{parts}")
            self.save_status.setObjectName("saveDone")
            self.save_btn.setText("もう一度画像にする")
        else:
            self.save_status.setText("この位置は、まだ画像にしていません")
            self.save_status.setObjectName("hint")
            self.save_btn.setText("この画面を画像にする")
        self._restyle(self.save_status)

    def _restyle(self, widget) -> None:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _set_saving(self, busy: bool) -> None:
        self._saving = busy
        self.save_progress.setVisible(busy)
        if busy:
            self.save_btn.setText("保存しています…")
            self.save_status.setText("保存しています…")
            self.save_status.setObjectName("hint")
            self._restyle(self.save_status)
            self.statusBar().showMessage("保存しています…")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self.save_btn.repaint()
            self.save_progress.repaint()
            self.save_status.repaint()
        else:
            QApplication.restoreOverrideCursor()
            self._refresh_save_status()

    def save_current(self) -> None:
        if self.info is None or self._saving:
            return
        kind = self._selected_kind()
        if kind is None:
            QMessageBox.information(self, "種類がありません", "先に種類を選んでください。")
            return
        self._set_saving(True)
        key, name = kind
        QTimer.singleShot(0, lambda: self._save_current_body(key, name))

    def _save_current_body(self, key: str, name: str) -> None:
        error: tuple[str, str] | None = None
        saved_text: str | None = None
        dest_name = ""
        try:
            if self.info is None:
                error = ("保存できませんでした", "動画がありません。")
                return
            image = self._read_frame(self._frame)
            if image is None:
                error = ("保存できませんでした", "この位置の画像を取得できませんでした。")
                return
            dest = self._unique_dest(self._frame / self.info.fps, key)
            try:
                write_image(dest, image)
            except Exception as exc:  # noqa: BLE001
                error = ("保存できませんでした", str(exc))
                return
            dest_name = dest.name
            saved = self._saved_at.setdefault(self._frame, [])
            saved.append((name, dest_name))
            labels = getattr(self._host, "scene_labels", None)
            if labels is not None:
                try:
                    labels.add(dest, key)
                except Exception:
                    pass
                refresh = getattr(self._host, "_refresh_teach_label", None)
                if callable(refresh):
                    refresh()
            extra = ""
            try:
                from app.handoff import send_images_to_tsumtsum

                result = send_images_to_tsumtsum([dest])
                extra = (
                    "\nツムツムアプリの一覧にも渡しました。"
                    if result == "sent"
                    else "\nツムツムアプリを開いて取り込みました。"
                )
            except Exception as exc:  # noqa: BLE001
                extra = f"\nツム側には渡せませんでした。\n{exc}"
            hint = ""
            if key == OTHER_KEY:
                hint = "\nリザルト画面なら、種類を result にすると result の学習からも開けます。"
            reflected = ""
            adder = getattr(self._host, "add_captured_scene", None)
            if callable(adder) and adder(key, self._frame, dest):
                reflected = "\n抜き出し位置にも載せました。"
            saved_text = f"種類: {name}\n{dest.name}\n{dest.parent}{extra}{hint}{reflected}"
        finally:
            self._set_saving(False)
        if error is not None:
            QMessageBox.warning(self, error[0], error[1])
            return
        if saved_text is None:
            return
        self.statusBar().showMessage(f"「{name}」で保存しました  {dest_name}", 6000)
        QMessageBox.information(self, "保存しました", saved_text)

    def _unique_dest(self, seconds: float, kind: str) -> Path:
        stamp = format_timecode(seconds).replace(":", "-")
        stem = self.info.path.stem if self.info is not None else "scene"
        slug = kind or "scene"
        dest = kind_dir(self.output_dir, slug) / f"{stem}_{stamp}.png"
        index = 2
        while dest.exists():
            dest = kind_dir(self.output_dir, slug) / f"{stem}_{stamp}_{index}.png"
            index += 1
        return dest

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

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_preview()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop_play()
        self._release_cap()
        event.accept()
