from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer
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
from app.regions import (
    PIECE_KEYS,
    PLACE_LABELS,
    PLACE_SPECS,
    REGION_KEYS,
    REGION_LABELS,
    is_piece_key,
)
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
QLabel#toast {
    background: rgba(31, 138, 91, 230);
    color: #f2f5f8;
    font-size: 22px;
    font-weight: 700;
    padding: 18px 32px;
    border-radius: 12px;
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
QScrollBar:vertical {
    background: #101216;
    width: 14px;
    margin: 2px;
    border-radius: 7px;
}
QScrollBar::handle:vertical {
    background: #5a6270;
    min-height: 32px;
    border-radius: 6px;
}
QScrollBar::handle:vertical:hover { background: #7a8494; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    height: 14px;
    background: #101216;
    margin: 2px;
    border-radius: 7px;
}
QScrollBar::handle:horizontal {
    background: #5a6270;
    min-width: 32px;
    border-radius: 6px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
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
        self.predictor = Predictor(self.dataset.models_dir)
        self.current_id: str | None = None
        self._active_key = "game"
        self.train_worker: TrainWorker | None = None
        self._dirty = False
        self._switching = False
        self._extractor_process = None
        self._ipc_buffers: dict[int, bytes] = {}
        self._last_boxes: dict[str, dict[str, int]] = {}
        self._last_piece_radius: dict[str, int] = {}
        self._remember_last_boxes()

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
        self.hint_label = QLabel("画像をドロップ / Ctrl+V / 「画像を開く」。左で場所の種類を選び、ドラッグで囲みます。")
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
        self.next_btn = QPushButton("次へ")
        self.prev_btn = QPushButton("前へ")
        self.clear_btn = QPushButton("この場所を消す")
        self.predict_btn = QPushButton("この画像を予測")
        self.train_btn = QPushButton("学習する")
        self.train_btn.setObjectName("primary")
        for button in (
            self.open_btn,
            self.paste_btn,
            self.confirm_btn,
            self.skip_btn,
            self.prev_btn,
            self.next_btn,
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
        side_layout.addWidget(QLabel("教える場所"))
        self.region_list = QListWidget()
        self.region_list.setMaximumHeight(210)
        for key, label, color in PLACE_SPECS:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setForeground(QColor(color))
            self.region_list.addItem(item)
        self.region_list.setCurrentRow(0)
        side_layout.addWidget(self.region_list)
        side_layout.addWidget(QLabel("データセット"))
        self.stats_label = QLabel()
        self.stats_label.setObjectName("hint")
        self.stats_label.setWordWrap(True)
        side_layout.addWidget(self.stats_label)
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.list_widget.setUniformItemSizes(True)
        side_layout.addWidget(self.list_widget, 1)
        self.delete_btn = QPushButton("選択を削除")
        side_layout.addWidget(self.delete_btn)
        self.copy_data_btn = QPushButton("dataをコピー")
        side_layout.addWidget(self.copy_data_btn)
        self.import_data_btn = QPushButton("dataを取り込む")
        side_layout.addWidget(self.import_data_btn)
        self.video_app_btn = QPushButton("動画から画像を抜き出す")
        side_layout.addWidget(self.video_app_btn)
        self.model_label = QLabel()
        self.model_label.setObjectName("hint")
        self.model_label.setWordWrap(True)
        side_layout.addWidget(self.model_label)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        side_layout.addWidget(self.progress)
        sidebar.setMinimumWidth(300)
        sidebar.setMaximumWidth(560)

        self.canvas = ImageCanvas()
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._toast = QLabel(self.canvas)
        self._toast.setObjectName("toast")
        self._toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._toast.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_save_toast)
        splitter.addWidget(sidebar)
        splitter.addWidget(self.canvas)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 860])
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
        self.reuse_btn = QPushButton("同じ枠を使う")
        coords_layout.addWidget(self.reuse_btn)
        coords_layout.addWidget(QLabel("ツム種類"))
        self.spin_group = QSpinBox()
        self.spin_group.setPrefix("No.  ")
        self.spin_group.setRange(1, 12)
        self.spin_group.setValue(1)
        coords_layout.addWidget(self.spin_group)
        self.piece_count_label = QLabel()
        self.piece_count_label.setObjectName("hint")
        coords_layout.addWidget(self.piece_count_label, 1)
        self.coords_hint = QLabel("上下キーで画像を切替  /  左右キーで枠を1px  /  Shift+矢印で10px  /  Ctrl+矢印でサイズ")
        self.coords_hint.setObjectName("hint")
        coords_layout.addWidget(self.coords_hint, 1)
        layout.addWidget(coords)

        self.setCentralWidget(root)
        self.statusBar().showMessage("準備完了")

        self.open_btn.clicked.connect(self.open_files)
        self.paste_btn.clicked.connect(self.paste_clipboard)
        self.confirm_btn.clicked.connect(self.confirm_current)
        self.skip_btn.clicked.connect(self.skip_current)
        self.next_btn.clicked.connect(self.go_next_image)
        self.prev_btn.clicked.connect(self.go_prev_image)
        self.clear_btn.clicked.connect(self.clear_current_region)
        self.reuse_btn.clicked.connect(self.reuse_last_box)
        self.predict_btn.clicked.connect(self.predict_current)
        self.train_btn.clicked.connect(self.start_training)
        self.delete_btn.clicked.connect(self.delete_current)
        self.copy_data_btn.clicked.connect(self.copy_data_folder)
        self.import_data_btn.clicked.connect(self.import_data_folder)
        self.video_app_btn.clicked.connect(self.launch_video_extractor)
        self.list_widget.currentItemChanged.connect(self.on_item_changed)
        self.region_list.currentItemChanged.connect(self.on_region_type_changed)
        self.canvas.regionCommitted.connect(self.on_region_committed)
        self.canvas.regionChanged.connect(self.on_region_changed)
        self.canvas.piecesChanged.connect(self.on_pieces_changed)
        self.canvas.pieceGroupChanged.connect(self.on_piece_group_changed)
        self.canvas.filesDropped.connect(self.import_paths)
        self.canvas.imageDropped.connect(self.import_qimage)
        self.canvas.installEventFilter(self)
        self.spin_group.valueChanged.connect(self.on_group_changed)
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
            if sample.status == "skipped":
                item.setForeground(QColor("#7a8190"))
            elif self._sample_has_active(sample):
                item.setForeground(QColor("#3DDC97"))
            elif not is_piece_key(self._active_key) and self._active_key in sample.regions:
                item.setForeground(QColor("#FFB020"))
            else:
                item.setForeground(QColor("#c5cad3"))
            self.list_widget.addItem(item)
            if selected and sample.id == selected:
                self.list_widget.setCurrentItem(item)
        self.list_widget.blockSignals(False)
        if selected is None and self.list_widget.count():
            self.list_widget.setCurrentRow(self.list_widget.count() - 1)
        self.update_stats()

    def _sample_has_active(self, sample: Sample) -> bool:
        if is_piece_key(self._active_key):
            return any(piece.get("kind") == self._active_key for piece in sample.pieces)
        return self._active_key in sample.confirmed

    def _item_text(self, sample: Sample) -> str:
        name = PLACE_LABELS.get(self._active_key, "範囲")
        if sample.status == "skipped":
            mark = "パス"
        elif self._sample_has_active(sample):
            mark = f"{name}済"
        elif not is_piece_key(self._active_key) and self._active_key in sample.regions:
            mark = f"{name}予測"
        else:
            mark = f"{name}未"
        return f"{mark}  {sample.source_name}"

    def update_stats(self) -> None:
        counts = self.dataset.counts()
        labeled_counts = self.dataset.labeled_counts()
        per_type = "  ".join(
            f"{PLACE_LABELS[key]} {labeled_counts[key]}" for key in [*REGION_KEYS, *PIECE_KEYS]
        )
        self.stats_label.setText(
            f"全 {counts['total']} 枚\n"
            f"保存済み {counts['labeled']} / 予測 {counts['predicted']} / 未設定 {counts['unlabeled']} / パス {counts['skipped']}\n"
            f"{per_type}\n"
            f"学習の目安: 種類ごとに {MIN_TRAIN_SAMPLES} 枚以上"
        )
        ready = self.predictor.ready_keys()
        if ready:
            names = "、".join(REGION_LABELS[key] for key in ready)
            self.model_label.setText(f"モデル: {names}。新しい画像には自動で予測します。")
        else:
            self.model_label.setText("モデル: まだありません。範囲を教えてから学習してください。")
        self.train_btn.setEnabled(bool(self._trainable_jobs()) and self.train_worker is None)
        has_sample = self.current_id is not None
        has_active = (
            bool(self.canvas.all_pieces())
            if is_piece_key(self._active_key)
            else self.canvas.current_region() is not None
        )
        has_boxes = bool(self.canvas.all_region_boxes()) or bool(self.canvas.all_pieces()) or (
            not is_piece_key(self._active_key) and self.canvas.current_region() is not None
        )
        self.confirm_btn.setEnabled(has_sample and has_boxes)
        self.confirm_btn.setText("この範囲を保存" if self._needs_save() else "保存済み")
        self.skip_btn.setEnabled(has_sample)
        self.next_btn.setEnabled(has_sample and self._unlabeled_id(self.current_id) is not None)
        self.prev_btn.setEnabled(has_sample and self._unlabeled_id(self.current_id, backward=True) is not None)
        self.clear_btn.setEnabled(has_sample and has_active)
        self.clear_btn.setText(f"{PLACE_LABELS.get(self._active_key, '範囲')}を消す")
        piece_mode = is_piece_key(self._active_key)
        self.spin_group.setEnabled(self._active_key == "tsum")
        has_last = (
            self._active_key in self._last_piece_radius
            if piece_mode
            else self._active_key in self._last_boxes
        )
        self.reuse_btn.setEnabled(has_sample and has_last)
        name = PLACE_LABELS.get(self._active_key, "範囲")
        self.reuse_btn.setText(f"{name}の大きさを使う" if piece_mode else f"{name}の枠を使う")
        counts_map = self.canvas.piece_counts()
        if counts_map:
            self.piece_count_label.setText("  ".join(f"{k} {v}" for k, v in counts_map.items()))
        else:
            self.piece_count_label.setText("")
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
            self._refresh_region_list()
            self.update_stats()
            return
        self.show_sample(current.data(Qt.ItemDataRole.UserRole))

    def on_region_type_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        key = current.data(Qt.ItemDataRole.UserRole)
        if not key:
            return
        self._active_key = key
        self.canvas.set_active_key(key)
        self._sync_spins_from_canvas()
        self._refresh_region_list()
        self.refresh_list(select_id=self.current_id)

    def _sync_spins_from_canvas(self) -> None:
        rect = self.canvas.current_region()
        if rect is None:
            self._set_spins(None)
            return
        self._set_spins(
            {
                "x": int(round(rect.x())),
                "y": int(round(rect.y())),
                "w": int(round(rect.width())),
                "h": int(round(rect.height())),
            }
        )

    def _refresh_region_list(self) -> None:
        boxes = self.canvas.all_region_boxes() if self.canvas.has_image() else {}
        pieces = self.canvas.all_pieces() if self.canvas.has_image() else []
        self.region_list.blockSignals(True)
        selected = None
        for row in range(self.region_list.count()):
            item = self.region_list.item(row)
            key = item.data(Qt.ItemDataRole.UserRole)
            label = PLACE_LABELS.get(key, key)
            if is_piece_key(key):
                has = any(piece.get("kind") == key for piece in pieces)
            else:
                has = key in boxes
            item.setText(f"{label}  ✓" if key == self._active_key and has else label)
            if key == self._active_key:
                selected = item
        if selected is not None:
            self.region_list.setCurrentItem(selected)
        self.region_list.blockSignals(False)

    def show_sample(self, sample_id: str) -> None:
        sample = self.dataset.get(sample_id)
        if sample is None:
            return
        self.current_id = sample.id
        pixmap = QPixmap(str(sample.image_path))
        regions = {
            key: QRectF(box["x"], box["y"], box["w"], box["h"])
            for key, box in sample.regions.items()
        }
        self.canvas.set_image(
            pixmap,
            None,
            sample.status,
            regions=regions,
            active_key=self._active_key,
            pieces=sample.pieces,
        )
        self.canvas.setFocus()
        self._sync_spins_from_canvas()
        self._set_dirty(False)
        self._refresh_region_list()
        if sample.status == "unlabeled":
            self.hint_label.setText("左の「教える場所」で種類を選び、ドラッグで囲みます。全部できたら「この範囲を保存」。使わないなら「この画像をパス」。")
        elif sample.status == "predicted":
            self.hint_label.setText("オレンジはゲーム範囲の予測です。他の場所も左から選んで囲めます。保存するか、使わないなら「この画像をパス」。")
        elif sample.status == "skipped":
            self.hint_label.setText("この画像はパス済みです。囲んで保存すれば学習に使えます。")
        else:
            self.hint_label.setText("色つきの四角が保存済みです。直したあとはもう一度「この範囲を保存」を押してください。")
        self.update_stats()

    def _remember_last_boxes(self) -> None:
        self._last_boxes = {}
        self._last_piece_radius = {}
        for sample in self.dataset.all():
            for key in sample.confirmed:
                box = sample.regions.get(key)
                if box:
                    self._last_boxes[key] = dict(box)
            for piece in sample.pieces:
                kind = str(piece.get("kind") or "")
                if kind in PIECE_KEYS:
                    self._last_piece_radius[kind] = int(piece["r"])

    def reuse_last_box(self) -> None:
        if not self.current_id:
            return
        name = PLACE_LABELS.get(self._active_key, "範囲")
        if is_piece_key(self._active_key):
            radius = self._last_piece_radius.get(self._active_key)
            if not radius:
                self.statusBar().showMessage(
                    f"「{name}」の大きさがまだありません。先に1つ付けて保存してください",
                    4000,
                )
                return
            self.canvas.set_default_radius(self._active_key, radius)
            self._set_dirty(True)
            self.statusBar().showMessage(f"「{name}」の大きさを {radius}px にしました", 4000)
            return
        box = self._last_boxes.get(self._active_key)
        if not box:
            self.statusBar().showMessage(
                f"「{name}」の枠がまだありません。先に1枚囲んで保存してください",
                4000,
            )
            return
        self.canvas.set_region(
            QRectF(box["x"], box["y"], box["w"], box["h"]),
            status="labeled",
            emit=False,
        )
        self._sync_spins_from_canvas()
        self._set_dirty(True)
        self._refresh_region_list()
        self.statusBar().showMessage(
            f"「{name}」の前の枠を載せました。位置を直して保存してください",
            4000,
        )

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
                    boxes = self.predictor.predict_all(sample.image_path)
                    if self.dataset.apply_predictions(sample.id, boxes):
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
        self._refresh_region_list()

    def on_region_committed(self, x: int, y: int, w: int, h: int) -> None:
        self._set_spins({"x": x, "y": y, "w": w, "h": h})
        self._set_dirty(True)
        self._refresh_region_list()
        name = PLACE_LABELS.get(self._active_key, "範囲")
        self.statusBar().showMessage(f"「{name}」はまだ保存していません。「この範囲を保存」を押すと確定します", 4000)

    def on_pieces_changed(self) -> None:
        self._set_dirty(True)
        self._refresh_region_list()
        self.update_stats()

    def on_group_changed(self, value: int) -> None:
        self.canvas.set_piece_group(value)

    def on_piece_group_changed(self, value: int) -> None:
        self.spin_group.blockSignals(True)
        self.spin_group.setValue(value)
        self.spin_group.blockSignals(False)

    def _set_dirty(self, dirty: bool) -> None:
        changed = self._dirty != dirty
        self._dirty = dirty
        self.confirm_btn.setText("この範囲を保存" if dirty or self._needs_save() else "保存済み")
        if changed:
            self.update_stats()
        else:
            has_region = self.canvas.current_region() is not None
            has_boxes = bool(self.canvas.all_region_boxes()) or has_region
            self.confirm_btn.setEnabled(self.current_id is not None and has_boxes)

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
        if not self.current_id or is_piece_key(self._active_key):
            return
        x, y, w, h = self.spin_x.value(), self.spin_y.value(), self.spin_w.value(), self.spin_h.value()
        self.canvas.set_region(QRectF(x, y, w, h), status="labeled", emit=False)
        self._set_dirty(True)

    def confirm_current(self) -> None:
        self.save_current_region()

    def save_current_region(self) -> bool:
        if not self.current_id:
            return False
        boxes = self.canvas.all_region_boxes()
        pieces = self.canvas.all_pieces()
        if not boxes and not pieces:
            QMessageBox.information(self, "範囲がありません", "先に左の種類を選んで囲むか、ツムに〇を付けてください。")
            return False
        sample = self.dataset.get(self.current_id)
        already = (
            not self._dirty
            and sample is not None
            and sample.regions == boxes
            and sample.pieces == pieces
        )
        if already:
            QMessageBox.information(
                self,
                "すでに保存済みです",
                "いま画面にある四角と〇は保存できています。\n"
                "直したあとにもう一度押せば上書きされます。",
            )
            return True
        self.dataset.set_regions(self.current_id, boxes, pieces=pieces)
        for key, box in boxes.items():
            self._last_boxes[key] = dict(box)
        for piece in pieces:
            self._last_piece_radius[str(piece["kind"])] = int(piece["r"])
        self._set_dirty(False)
        self.refresh_list(select_id=self.current_id)
        self._refresh_region_list()
        self.update_stats()
        names = "、".join(PLACE_LABELS.get(key, key) for key in boxes)
        if pieces:
            tsum_n = sum(1 for piece in pieces if piece["kind"] == "tsum")
            bomb_n = sum(1 for piece in pieces if piece["kind"] == "bomb")
            extra = []
            if tsum_n:
                extra.append(f"ツム{tsum_n}")
            if bomb_n:
                extra.append(f"ボム{bomb_n}")
            names = "、".join([n for n in [names, *extra] if n])
        self.statusBar().showMessage(f"保存しました: {names}", 4000)
        self._show_save_toast(names)
        return True

    def _show_save_toast(self, names: str) -> None:
        text = "保存しました" if not names else f"保存しました\n{names}"
        self._toast.setText(text)
        self._toast.adjustSize()
        x = max(12, (self.canvas.width() - self._toast.width()) // 2)
        y = max(12, (self.canvas.height() - self._toast.height()) // 2)
        self._toast.move(x, y)
        self._toast.show()
        self._toast.raise_()
        self.confirm_btn.setText("保存しました")
        self._toast_timer.start(1600)

    def _hide_save_toast(self) -> None:
        self._toast.hide()
        self.confirm_btn.setText("この範囲を保存" if self._needs_save() else "保存済み")

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
        if is_piece_key(self._active_key):
            self.canvas.clear_pieces_of_kind(self._active_key)
        else:
            self.canvas.set_region(None)
        self.dataset.clear_named_region(self.current_id, self._active_key)
        sample = self.dataset.get(self.current_id)
        saved_boxes = sample.regions if sample else {}
        saved_pieces = sample.pieces if sample else []
        self._set_dirty(
            self.canvas.all_region_boxes() != saved_boxes or self.canvas.all_pieces() != saved_pieces
        )
        self.refresh_list(select_id=self.current_id)
        self._sync_spins_from_canvas()
        self._refresh_region_list()
        self.update_stats()
        name = PLACE_LABELS.get(self._active_key, "範囲")
        self.statusBar().showMessage(f"「{name}」を消しました", 3000)

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

    def copy_data_folder(self) -> None:
        if not DATA_DIR.exists():
            QMessageBox.warning(self, "dataがありません", f"コピーするフォルダがありません。\n{DATA_DIR}")
            return
        dest_parent = QFileDialog.getExistingDirectory(self, "貼り付ける場所を選ぶ", str(Path.home()))
        if not dest_parent:
            return
        dest = Path(dest_parent) / DATA_DIR.name
        try:
            if dest.resolve() == DATA_DIR.resolve():
                QMessageBox.information(self, "同じ場所です", "コピー元と同じ場所です。")
                return
        except OSError:
            pass
        if dest.exists():
            answer = QMessageBox.question(
                self,
                "すでにあります",
                f"{dest}\nすでに data フォルダがあります。中身を置き換えますか？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            shutil.rmtree(dest)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            shutil.copytree(DATA_DIR, dest)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "コピーに失敗", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(f"dataをコピーしました: {dest}", 5000)

    def _resolve_data_dir(self, path: Path) -> Path | None:
        if (path / "index.json").exists() or (path / "images").is_dir() or (path / "models").is_dir():
            return path
        inner = path / "data"
        if (inner / "index.json").exists() or (inner / "images").is_dir() or (inner / "models").is_dir():
            return inner
        return None

    def import_data_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "取り込む data を選ぶ", str(Path.home()))
        if not chosen:
            return
        source = self._resolve_data_dir(Path(chosen))
        if source is None:
            QMessageBox.warning(
                self,
                "dataではありません",
                "index.json か images か models があるフォルダを選んでください。",
            )
            return
        try:
            if source.resolve() == DATA_DIR.resolve():
                QMessageBox.information(self, "同じ場所です", "今使っている data と同じ場所です。")
                return
        except OSError:
            pass
        answer = QMessageBox.question(
            self,
            "dataを取り込む",
            "今の画像・枠・モデルを、選んだ data で置き換えます。続けますか？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self._confirm_discard():
            return
        self.current_id = None
        self.canvas.clear_image()
        QApplication.processEvents()
        tmp = DATA_DIR.parent / "_data_importing"
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if tmp.exists():
                shutil.rmtree(tmp)
            shutil.copytree(source, tmp)
            if DATA_DIR.exists():
                shutil.rmtree(DATA_DIR)
            tmp.rename(DATA_DIR)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "取り込みに失敗", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
        self.dataset.reload()
        self.predictor.reload()
        self._remember_last_boxes()
        self.refresh_list()
        self.statusBar().showMessage("dataを取り込みました", 5000)

    def predict_current(self) -> None:
        if not self.current_id or not self.predictor.is_ready():
            return
        sample = self.dataset.get(self.current_id)
        if sample is None:
            return
        try:
            boxes = self.predictor.predict_all(sample.image_path)
            added = self.dataset.apply_predictions(sample.id, boxes)
            self.refresh_list(select_id=sample.id)
            self.show_sample(sample.id)
            if added:
                names = "、".join(REGION_LABELS.get(key, key) for key in added)
                self.statusBar().showMessage(f"予測を入れました: {names}。合っていれば保存してください", 4000)
            else:
                self.statusBar().showMessage("保存済みの場所はそのままです。足りない場所はありませんでした", 4000)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "予測に失敗", str(exc))

    def _trainable_jobs(self) -> list[tuple[str, list, object]]:
        jobs = []
        for key in REGION_KEYS:
            samples = self.dataset.labeled_for(key)
            if len(samples) >= MIN_TRAIN_SAMPLES:
                jobs.append((key, samples, self.dataset.model_path_for(key)))
        return jobs

    def _needs_save(self) -> bool:
        if self._dirty:
            return True
        if not self.current_id or not self.canvas.has_image():
            return False
        sample = self.dataset.get(self.current_id)
        if sample is None:
            return False
        boxes = self.canvas.all_region_boxes()
        pieces = self.canvas.all_pieces()
        return sample.regions != boxes or sample.pieces != pieces

    def start_training(self) -> None:
        jobs = self._trainable_jobs()
        counts = self.dataset.labeled_counts()
        if not jobs:
            lines = [
                f"学習には種類ごとに正解が {MIN_TRAIN_SAMPLES} 枚以上必要です。",
                "",
            ]
            lines.extend(f"{REGION_LABELS[key]}: {counts[key]} 枚" for key in REGION_KEYS)
            QMessageBox.information(self, "まだ足りません", "\n".join(lines))
            return
        ready_lines = [
            f"{REGION_LABELS[key]}: {len(samples)} 枚" for key, samples, _path in jobs
        ]
        skipped = [
            f"{REGION_LABELS[key]}: {counts[key]} 枚" for key in REGION_KEYS if counts[key] < MIN_TRAIN_SAMPLES
        ]
        message = "次の場所を学習します。\n" + "\n".join(ready_lines)
        if skipped:
            message += "\n\n枚数が足りない場所は今回スキップします。\n" + "\n".join(skipped)
        answer = QMessageBox.question(self, "学習を開始", message)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, 40 * len(jobs))
        self.progress.setValue(0)
        self.train_btn.setEnabled(False)
        self.train_worker = TrainWorker(jobs)
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
        results = metrics.get("results") or []
        lines = [
            f"{item['label']}  IoU {item['iou']:.3f}（{item['samples']} 枚）" for item in results
        ]
        QMessageBox.information(
            self,
            "学習完了",
            "\n".join(lines) + f"\n\n未設定の箇所 {applied} 件に予測を入れました。",
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
        for sample in self.dataset.all():
            if sample.status == "skipped":
                continue
            try:
                boxes = self.predictor.predict_all(sample.image_path)
                added = self.dataset.apply_predictions(sample.id, boxes)
            except Exception:
                continue
            applied += len(added)
        return applied

    def eventFilter(self, watched, event) -> bool:
        if (
            watched is self.canvas
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down)
            and event.modifiers()
            in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)
        ):
            self._select_image_by_delta(-1 if event.key() == Qt.Key.Key_Up else 1)
            return True
        return super().eventFilter(watched, event)

    def _select_image_by_delta(self, delta: int) -> None:
        count = self.list_widget.count()
        if count <= 0:
            return
        row = self.list_widget.currentRow()
        if row < 0:
            next_row = 0 if delta > 0 else count - 1
        else:
            next_row = row + delta
        if next_row < 0 or next_row >= count:
            return
        self.list_widget.setCurrentRow(next_row)

    def _unlabeled_id(self, after_id: str | None, *, backward: bool = False) -> str | None:
        samples = self.dataset.all()
        if backward:
            samples = list(reversed(samples))
        if not samples:
            return None

        def pending(sample: Sample) -> bool:
            if sample.status == "skipped":
                return False
            if is_piece_key(self._active_key):
                return not any(piece.get("kind") == self._active_key for piece in sample.pieces)
            return self._active_key not in sample.confirmed

        ids = [sample.id for sample in samples]
        if after_id is None or after_id not in ids:
            for sample in samples:
                if pending(sample):
                    return sample.id
            return None
        start = ids.index(after_id)
        for sample in samples[start + 1 :] + samples[: start + 1]:
            if sample.id != after_id and pending(sample):
                return sample.id
        return None

    def _select_image_id(self, sample_id: str) -> None:
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == sample_id:
                self.list_widget.setCurrentRow(row)
                return

    def go_next_image(self) -> None:
        self._go_unlabeled_image(backward=False)

    def go_prev_image(self) -> None:
        self._go_unlabeled_image(backward=True)

    def _go_unlabeled_image(self, *, backward: bool) -> None:
        next_id = self._unlabeled_id(self.current_id, backward=backward)
        name = REGION_LABELS.get(self._active_key, "範囲")
        if next_id is None:
            self.statusBar().showMessage(f"「{name}」が未の画像はありません", 4000)
            return
        self._select_image_id(next_id)

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
