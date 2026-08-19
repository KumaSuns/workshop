from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QColor, QDragEnterEvent, QDropEvent, QKeySequence, QPixmap, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
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

from app.dataset import Dataset, Sample
from app.image_canvas import ImageCanvas
from app.paths import DATA_DIR, IMAGE_EXTENSIONS, IPC_NAME, VIDEO_EXTRACTOR_MAIN
from app.predictor import Predictor
from app.train_worker import MIN_TRAIN_SAMPLES, TrainWorker

STYLESHEET = """
QMainWindow, QWidget {
    background: #16181d;
    color: #e8eaed;
    font-family: "Yu Gothic UI", "Segoe UI", sans-serif;
    font-size: 13px;
}
QLabel#title {
    font-size: 18px;
    font-weight: 700;
}
QLabel#hint {
    color: #9aa3b2;
}
QPushButton {
    background: #2a303b;
    color: #e8eaed;
    border: none;
    padding: 8px 14px;
    border-radius: 8px;
}
QPushButton:hover { background: #3a4250; }
QPushButton:disabled { color: #6b7380; background: #22262e; }
QPushButton#primary {
    background: #5b6cff;
    font-weight: 600;
}
QPushButton#primary:hover { background: #6e7dff; }
QPushButton#accent {
    background: #1f8a5b;
    font-weight: 600;
}
QPushButton#accent:hover { background: #27a36c; }
QListWidget {
    background: #101216;
    border: 1px solid #2a303b;
    border-radius: 10px;
    padding: 6px;
    outline: none;
}
QListWidget::item {
    padding: 8px 10px;
    border-radius: 6px;
}
QListWidget::item:selected {
    background: #2c3344;
}
QFrame#sidebar, QFrame#topbar {
    background: #1c2028;
    border: 1px solid #2a303b;
    border-radius: 12px;
}
QProgressBar {
    background: #101216;
    border: 1px solid #2a303b;
    border-radius: 6px;
    text-align: center;
    color: #e8eaed;
    height: 18px;
}
QProgressBar::chunk {
    background: #5b6cff;
    border-radius: 6px;
}
QStatusBar { color: #9aa3b2; }
QSpinBox {
    background: #101216;
    color: #e8eaed;
    border: 1px solid #2a303b;
    border-radius: 6px;
    padding: 4px 8px;
    min-width: 92px;
}
QFrame#coords {
    background: #1c2028;
    border: 1px solid #2a303b;
    border-radius: 12px;
}
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ツムツム ゲーム範囲トレーナー")
        self.resize(1280, 840)
        self.setMinimumSize(980, 640)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLESHEET)

        self.dataset = Dataset(DATA_DIR)
        self.predictor = Predictor(self.dataset.model_path)
        self.current_id: str | None = None
        self.train_worker: TrainWorker | None = None
        self._dirty = False
        self._switching = False
        self._extractor_process = None
        self._ipc_buffers: dict[int, bytes] = {}

        self._build_ui()
        self._bind_shortcuts()
        self._start_ipc()
        self.refresh_list()
        self.update_stats()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        top = QFrame()
        top.setObjectName("topbar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(16, 12, 16, 12)
        title_box = QVBoxLayout()
        title = QLabel("ツムツム ゲーム範囲トレーナー")
        title.setObjectName("title")
        self.hint_label = QLabel("画像をドロップ / Ctrl+V / 「画像を開く」。表示されたらドラッグで囲み、角を引っ張って微調整できます。")
        self.hint_label.setObjectName("hint")
        self.hint_label.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(self.hint_label)
        top_layout.addLayout(title_box, 1)

        self.open_btn = QPushButton("画像を開く")
        self.paste_btn = QPushButton("貼り付け")
        self.confirm_btn = QPushButton("この範囲を保存")
        self.confirm_btn.setObjectName("accent")
        self.skip_btn = QPushButton("この画像をパス")
        self.clear_btn = QPushButton("範囲を消す")
        self.predict_btn = QPushButton("この画像を予測")
        self.train_btn = QPushButton("学習する")
        self.train_btn.setObjectName("primary")
        for button in (
            self.open_btn,
            self.paste_btn,
            self.confirm_btn,
            self.skip_btn,
            self.clear_btn,
            self.predict_btn,
            self.train_btn,
        ):
            top_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 12, 12, 12)
        side_layout.addWidget(QLabel("データセット"))
        self.stats_label = QLabel()
        self.stats_label.setObjectName("hint")
        self.stats_label.setWordWrap(True)
        side_layout.addWidget(self.stats_label)
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        side_layout.addWidget(self.list_widget, 1)
        self.delete_btn = QPushButton("選択を削除")
        side_layout.addWidget(self.delete_btn)
        self.video_app_btn = QPushButton("動画から画像を抜き出す")
        side_layout.addWidget(self.video_app_btn)
        self.model_label = QLabel()
        self.model_label.setObjectName("hint")
        self.model_label.setWordWrap(True)
        side_layout.addWidget(self.model_label)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        side_layout.addWidget(self.progress)
        sidebar.setMinimumWidth(260)
        sidebar.setMaximumWidth(360)

        self.canvas = ImageCanvas()
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        splitter.addWidget(sidebar)
        splitter.addWidget(self.canvas)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 980])
        layout.addWidget(splitter, 1)

        coords = QFrame()
        coords.setObjectName("coords")
        coords_layout = QHBoxLayout(coords)
        coords_layout.setContentsMargins(12, 8, 12, 8)
        coords_layout.addWidget(QLabel("微調整"))
        self.spin_x = self._make_spin("X")
        self.spin_y = self._make_spin("Y")
        self.spin_w = self._make_spin("W")
        self.spin_h = self._make_spin("H")
        for spin in (self.spin_x, self.spin_y, self.spin_w, self.spin_h):
            coords_layout.addWidget(spin)
        self.coords_hint = QLabel("矢印キーで1px移動  /  Shift+矢印で10px  /  Ctrl+矢印でサイズ変更")
        self.coords_hint.setObjectName("hint")
        coords_layout.addWidget(self.coords_hint, 1)
        layout.addWidget(coords)

        self.setCentralWidget(root)
        self.statusBar().showMessage("準備完了")

        self.open_btn.clicked.connect(self.open_files)
        self.paste_btn.clicked.connect(self.paste_clipboard)
        self.confirm_btn.clicked.connect(self.confirm_current)
        self.skip_btn.clicked.connect(self.skip_current)
        self.clear_btn.clicked.connect(self.clear_current_region)
        self.predict_btn.clicked.connect(self.predict_current)
        self.train_btn.clicked.connect(self.start_training)
        self.delete_btn.clicked.connect(self.delete_current)
        self.video_app_btn.clicked.connect(self.launch_video_extractor)
        self.list_widget.currentItemChanged.connect(self.on_item_changed)
        self.canvas.regionCommitted.connect(self.on_region_committed)
        self.canvas.regionChanged.connect(self.on_region_changed)
        self.canvas.filesDropped.connect(self.import_paths)
        self.canvas.imageDropped.connect(self.import_qimage)
        for spin in (self.spin_x, self.spin_y, self.spin_w, self.spin_h):
            spin.valueChanged.connect(self.on_spin_changed)

    def _make_spin(self, prefix: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setPrefix(f"{prefix}  ")
        spin.setRange(0, 20000)
        spin.setEnabled(False)
        return spin

    def _bind_shortcuts(self) -> None:
        QShortcut(QKeySequence.StandardKey.Save, self, self.confirm_current)
        skip = QShortcut(QKeySequence("P"), self)
        skip.activated.connect(self.skip_current)
        skip_space = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        skip_space.activated.connect(self.skip_current)
        QShortcut(QKeySequence.StandardKey.Paste, self, self.paste_clipboard)
        QShortcut(QKeySequence.StandardKey.Delete, self, self.delete_current)
        fit = QAction(self)
        fit.setShortcut(QKeySequence("F"))
        fit.triggered.connect(self.canvas.fit_to_view)
        self.addAction(fit)

    def _start_ipc(self) -> None:
        QLocalServer.removeServer(IPC_NAME)
        self._ipc_server = QLocalServer(self)
        self._ipc_server.newConnection.connect(self._on_ipc_connection)
        if not self._ipc_server.listen(IPC_NAME):
            self.statusBar().showMessage("他のウィンドウからの受け取り口を開けませんでした", 4000)

    def _on_ipc_connection(self) -> None:
        sock = self._ipc_server.nextPendingConnection()
        if sock is None:
            return
        self._ipc_buffers[id(sock)] = b""
        sock.readyRead.connect(lambda s=sock: self._on_ipc_ready(s))
        sock.disconnected.connect(lambda s=sock: self._ipc_buffers.pop(id(s), None))

    def _on_ipc_ready(self, sock: QLocalSocket) -> None:
        self._ipc_buffers[id(sock)] = self._ipc_buffers.get(id(sock), b"") + bytes(sock.readAll())
        buffer = self._ipc_buffers[id(sock)]
        if b"\n" not in buffer:
            return
        line, rest = buffer.split(b"\n", 1)
        self._ipc_buffers[id(sock)] = rest
        try:
            payload = json.loads(line.decode("utf-8"))
            paths = [str(path) for path in payload.get("paths", [])]
        except Exception:
            sock.write(b'{"ok":false}\n')
            sock.flush()
            return
        sock.write(b'{"ok":true}\n')
        sock.flush()
        self.import_incoming_paths(paths)

    def import_incoming_paths(self, paths: list[str]) -> None:
        self._bring_to_front()
        self.import_paths(paths)

    def _bring_to_front(self) -> None:
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh_list(self, select_id: str | None = None) -> None:
        selected = select_id or self.current_id
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for sample in self.dataset.all():
            item = QListWidgetItem(self._item_text(sample))
            item.setData(Qt.ItemDataRole.UserRole, sample.id)
            if sample.status == "labeled":
                item.setForeground(QColor("#3DDC97"))
            elif sample.status == "predicted":
                item.setForeground(QColor("#FFB020"))
            elif sample.status == "skipped":
                item.setForeground(QColor("#7a8190"))
            self.list_widget.addItem(item)
            if selected and sample.id == selected:
                self.list_widget.setCurrentItem(item)
        self.list_widget.blockSignals(False)
        if selected is None and self.list_widget.count():
            self.list_widget.setCurrentRow(self.list_widget.count() - 1)
        self.update_stats()

    def _item_text(self, sample: Sample) -> str:
        mark = {
            "labeled": "保存済み",
            "predicted": "予測",
            "unlabeled": "未保存",
            "skipped": "パス",
        }.get(sample.status, "未保存")
        return f"{mark}  {sample.source_name}"

    def update_stats(self) -> None:
        counts = self.dataset.counts()
        self.stats_label.setText(
            f"全 {counts['total']} 枚\n"
            f"正解 {counts['labeled']} / 予測 {counts['predicted']} / 未設定 {counts['unlabeled']} / パス {counts['skipped']}\n"
            f"学習の目安: {MIN_TRAIN_SAMPLES} 枚以上"
        )
        if self.predictor.is_ready():
            self.model_label.setText("モデル: 学習済み。新しい画像には自動で範囲を予測します。")
        else:
            self.model_label.setText("モデル: まだありません。範囲を教えてから学習してください。")
        self.train_btn.setEnabled(
            len(self.dataset.labeled()) >= MIN_TRAIN_SAMPLES and self.train_worker is None
        )
        has_sample = self.current_id is not None
        has_region = self.canvas.current_region() is not None
        self.confirm_btn.setEnabled(has_sample and has_region)
        self.skip_btn.setEnabled(has_sample)
        self.clear_btn.setEnabled(has_sample and has_region)
        self.predict_btn.setEnabled(has_sample and self.predictor.is_ready())
        self.delete_btn.setEnabled(has_sample)

    def on_item_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if self._switching:
            return
        if not self._confirm_discard():
            self._switching = True
            self.list_widget.setCurrentItem(previous)
            self._switching = False
            return
        if current is None:
            self.current_id = None
            self.canvas.clear_image()
            self._set_spins(None)
            self._set_dirty(False)
            self.update_stats()
            return
        self.show_sample(current.data(Qt.ItemDataRole.UserRole))

    def show_sample(self, sample_id: str) -> None:
        sample = self.dataset.get(sample_id)
        if sample is None:
            return
        self.current_id = sample.id
        pixmap = QPixmap(str(sample.image_path))
        region = None
        if sample.game_region:
            r = sample.game_region
            region = QRectF(r["x"], r["y"], r["w"], r["h"])
        self.canvas.set_image(pixmap, region, sample.status)
        self.canvas.setFocus()
        self._set_spins(sample.game_region, sample.width, sample.height)
        self._set_dirty(False)
        if sample.status == "unlabeled":
            self.hint_label.setText("画像の上をドラッグして囲むか、使わないなら「この画像をパス」（P / Space）")
        elif sample.status == "predicted":
            self.hint_label.setText("オレンジは予測です。直して保存するか、使わないなら「この画像をパス」")
        elif sample.status == "skipped":
            self.hint_label.setText("この画像はパス済みです。囲んで保存すれば学習に使えます。")
        else:
            self.hint_label.setText("明るい部分が保存済みのゲーム範囲です。直したあとはもう一度「この範囲を保存」を押してください。")
        self.update_stats()

    def launch_video_extractor(self) -> None:
        script = VIDEO_EXTRACTOR_MAIN
        if not script.exists():
            QMessageBox.warning(
                self,
                "アプリが見つかりません",
                f"動画抜き出しアプリが見つかりません。\n{script}",
            )
            return
        kwargs: dict = {"cwd": str(script.parent)}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            self._extractor_process = subprocess.Popen(
                [sys.executable, str(script)],
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "起動に失敗", str(exc))
            return
        self.statusBar().showMessage("動画フレーム抜き出しを起動しました", 4000)

    def open_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "画像を開く",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if files:
            self.import_paths(files)

    def paste_clipboard(self) -> None:
        mime = QApplication.clipboard().mimeData()
        if mime.hasImage():
            self.import_qimage(mime.imageData())
            return
        if mime.hasUrls():
            paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
            if paths:
                self.import_paths(paths)
                return
        self.statusBar().showMessage("クリップボードに画像がありません", 3000)

    def import_paths(self, paths: list[str]) -> None:
        imported: list[Sample] = []
        for raw in paths:
            path = Path(raw)
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            try:
                imported.append(self.dataset.import_file(path))
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "読み込みに失敗", f"{path.name}\n{exc}")
        if not imported:
            return
        self._after_import(imported)

    def import_qimage(self, image) -> None:
        try:
            sample = self.dataset.import_qimage(image, "clipboard.png")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "貼り付けに失敗", str(exc))
            return
        self._after_import([sample])

    def _after_import(self, samples: list[Sample]) -> None:
        predicted = 0
        if self.predictor.is_ready():
            for sample in samples:
                if sample.status != "unlabeled":
                    continue
                try:
                    box = self.predictor.predict_path(sample.image_path)
                    self.dataset.set_region(sample.id, box["x"], box["y"], box["w"], box["h"], status="predicted")
                    predicted += 1
                except Exception:
                    continue
        last = samples[-1]
        first = next((sample.id for sample in samples if sample.status in {"unlabeled", "predicted"}), last.id)
        self.refresh_list(select_id=first)
        self.show_sample(first)
        if predicted:
            self.statusBar().showMessage(f"{len(samples)} 枚を取り込み、{predicted} 枚を予測しました", 4000)
        else:
            self.statusBar().showMessage(f"{len(samples)} 枚を取り込みました。範囲を囲んで「この範囲を保存」を押してください", 4000)

    def on_region_changed(self, x: int, y: int, w: int, h: int) -> None:
        self._set_spins({"x": x, "y": y, "w": w, "h": h})
        self._set_dirty(True)

    def on_region_committed(self, x: int, y: int, w: int, h: int) -> None:
        self._set_spins({"x": x, "y": y, "w": w, "h": h})
        self._set_dirty(True)
        self.statusBar().showMessage("まだ保存していません。「この範囲を保存」を押すと確定します", 4000)

    def _set_dirty(self, dirty: bool) -> None:
        changed = self._dirty != dirty
        self._dirty = dirty
        self.confirm_btn.setText("この範囲を保存" if dirty else "保存済み")
        if changed:
            self.update_stats()
        else:
            has_region = self.canvas.current_region() is not None
            self.confirm_btn.setEnabled(self.current_id is not None and has_region)

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "未保存の範囲",
            "囲んだ範囲はまだ保存していません。どうしますか？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_current_region()
        if answer == QMessageBox.StandardButton.Discard:
            self._set_dirty(False)
            return True
        return False

    def _set_spins(self, region: dict | None, width: int | None = None, height: int | None = None) -> None:
        for spin in (self.spin_x, self.spin_y, self.spin_w, self.spin_h):
            spin.blockSignals(True)
        sample = self.dataset.get(self.current_id) if self.current_id else None
        max_w = width or (sample.width if sample else 20000)
        max_h = height or (sample.height if sample else 20000)
        self.spin_x.setRange(0, max(0, max_w - 1))
        self.spin_y.setRange(0, max(0, max_h - 1))
        self.spin_w.setRange(1, max(1, max_w))
        self.spin_h.setRange(1, max(1, max_h))
        enabled = region is not None
        for spin in (self.spin_x, self.spin_y, self.spin_w, self.spin_h):
            spin.setEnabled(enabled)
        if region:
            self.spin_x.setValue(int(region["x"]))
            self.spin_y.setValue(int(region["y"]))
            self.spin_w.setValue(int(region["w"]))
            self.spin_h.setValue(int(region["h"]))
        for spin in (self.spin_x, self.spin_y, self.spin_w, self.spin_h):
            spin.blockSignals(False)

    def on_spin_changed(self) -> None:
        if not self.current_id:
            return
        x, y, w, h = self.spin_x.value(), self.spin_y.value(), self.spin_w.value(), self.spin_h.value()
        self.canvas.set_region(QRectF(x, y, w, h), status="labeled", emit=False)
        self._set_dirty(True)

    def confirm_current(self) -> None:
        self.save_current_region()

    def save_current_region(self) -> bool:
        if not self.current_id:
            return False
        rect = self.canvas.current_region()
        if rect is None:
            QMessageBox.information(self, "範囲がありません", "先にドラッグでゲーム範囲を囲んでください。")
            return False
        x, y, w, h = (int(round(rect.x())), int(round(rect.y())), int(round(rect.width())), int(round(rect.height())))
        sample = self.dataset.get(self.current_id)
        already = (
            not self._dirty
            and sample is not None
            and sample.status == "labeled"
            and sample.game_region == {"x": x, "y": y, "w": w, "h": h}
        )
        if already:
            QMessageBox.information(
                self,
                "すでに保存済みです",
                "この範囲は保存できています。何度押しても同じ1件のままです。\n"
                "左の一覧が「保存済み」になっていればOKです。",
            )
            return True
        self.dataset.set_region(self.current_id, x, y, w, h, status="labeled")
        self._set_dirty(False)
        remaining = self.dataset.next_pending(self.current_id)
        self._advance_after_action(f"ゲーム範囲を保存しました ({w}×{h})")
        if remaining is None:
            QMessageBox.information(
                self,
                "保存しました",
                f"ゲーム範囲を保存しました。\n{w} × {h} px\n未設定の画像はありません。",
            )
        return True

    def skip_current(self) -> None:
        if not self.current_id:
            return
        self._set_dirty(False)
        self.dataset.skip(self.current_id)
        self._advance_after_action("この画像をパスしました")

    def _advance_after_action(self, message: str) -> None:
        next_id = self.dataset.next_pending(self.current_id)
        self.refresh_list(select_id=next_id or self.current_id)
        if next_id:
            self.show_sample(next_id)
            self.statusBar().showMessage(f"{message}。次の画像です", 4000)
        elif self.current_id:
            self.show_sample(self.current_id)
            self.statusBar().showMessage(message, 4000)

    def clear_current_region(self) -> None:
        if not self.current_id:
            return
        self.dataset.clear_region(self.current_id)
        self.refresh_list(select_id=self.current_id)
        self.show_sample(self.current_id)

    def delete_current(self) -> None:
        if not self.current_id:
            return
        sample = self.dataset.get(self.current_id)
        name = sample.source_name if sample else self.current_id
        answer = QMessageBox.question(self, "削除", f"{name} をデータセットから削除しますか？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.dataset.remove(self.current_id)
        self.current_id = None
        self.canvas.clear_image()
        self.refresh_list()

    def predict_current(self) -> None:
        if not self.current_id or not self.predictor.is_ready():
            return
        sample = self.dataset.get(self.current_id)
        if sample is None:
            return
        try:
            box = self.predictor.predict_path(sample.image_path)
            self.dataset.set_region(sample.id, box["x"], box["y"], box["w"], box["h"], status="predicted")
            self.refresh_list(select_id=sample.id)
            self.show_sample(sample.id)
            self.statusBar().showMessage("予測を適用しました。合っていれば正解にしてください", 4000)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "予測に失敗", str(exc))

    def start_training(self) -> None:
        labeled = self.dataset.labeled()
        if len(labeled) < MIN_TRAIN_SAMPLES:
            QMessageBox.information(
                self,
                "まだ足りません",
                f"学習には正解の範囲が {MIN_TRAIN_SAMPLES} 枚以上必要です。いま {len(labeled)} 枚です。",
            )
            return
        answer = QMessageBox.question(
            self,
            "学習を開始",
            f"正解 {len(labeled)} 枚でゲーム範囲を学習します。枚数が少ないと精度は出にくいです。続けますか？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, 40)
        self.progress.setValue(0)
        self.train_btn.setEnabled(False)
        self.train_worker = TrainWorker(labeled, self.dataset.model_path)
        self.train_worker.progress.connect(self.on_train_progress)
        self.train_worker.finished_ok.connect(self.on_train_finished)
        self.train_worker.failed.connect(self.on_train_failed)
        self.train_worker.start()
        self.statusBar().showMessage("学習中です…")

    def on_train_progress(self, epoch: int, total: int, message: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(epoch)
        self.statusBar().showMessage(message)

    def on_train_finished(self, metrics: dict) -> None:
        self.train_worker = None
        self.progress.setVisible(False)
        self.predictor.reload()
        applied = self._apply_predictions_to_unlabeled()
        self.update_stats()
        self.refresh_list(select_id=self.current_id)
        if self.current_id:
            self.show_sample(self.current_id)
        QMessageBox.information(
            self,
            "学習完了",
            f"平均 IoU {metrics['iou']:.3f} で保存しました。\n"
            f"未設定の画像 {applied} 枚に予測を入れました。新しい画像でも試せます。",
        )
        self.statusBar().showMessage("学習が完了しました", 4000)

    def on_train_failed(self, message: str) -> None:
        self.train_worker = None
        self.progress.setVisible(False)
        self.update_stats()
        QMessageBox.critical(self, "学習に失敗", message)

    def _apply_predictions_to_unlabeled(self) -> int:
        if not self.predictor.is_ready():
            return 0
        applied = 0
        for sample in self.dataset.unlabeled():
            try:
                box = self.predictor.predict_path(sample.image_path)
                self.dataset.set_region(sample.id, box["x"], box["y"], box["w"], box["h"], status="predicted")
                applied += 1
            except Exception:
                continue
        return applied

    def closeEvent(self, event) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        if self.train_worker is not None and self.train_worker.isRunning():
            self.train_worker.wait(1000)
        event.accept()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        if mime.hasUrls():
            paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
            self.import_paths(paths)
            event.acceptProposedAction()
            return
        if mime.hasImage():
            self.import_qimage(mime.imageData())
            event.acceptProposedAction()
            return
        event.ignore()
