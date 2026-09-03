from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QEvent, QRect, QRectF, QSettings, QSize, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QIcon,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.dataset import Dataset, Sample
from app.hud_number import CoinNumberDialog, format_coin_number, read_coin_number as ocr_coin_number
from app.image_canvas import ImageCanvas
from app.paths import (
    APP_ROOT,
    DATA_DIR,
    DATA_SYNC_PATH,
    EXTRACTOR_IPC_NAME,
    IMAGE_EXTENSIONS,
    IPC_NAME,
    SERVER_SYNC_PATH,
    VIDEO_EXTRACTOR_MAIN,
)
from app.predictor import Predictor
from app.regions import (
    COIN_BOX_KEYS,
    PIECE_KEYS,
    PLACE_LABELS,
    PLACE_SPECS,
    REGION_KEYS,
    REGION_LABELS,
    SCENE_KEYS,
    is_coin_box_key,
    is_piece_key,
    is_scene_key,
    tsum_group_color,
)
from app.skill_export import registered_skills_by_sample, save_skill_image, skill_tsum_choices
from app.train_effect import TrainEffect
from app.train_worker import MIN_TRAIN_SAMPLES, TRAIN_EPOCHS, TrainWorker

LIST_STATUS_WIDTHS = {
    "game": 36,
    "score": 36,
    "coin": 36,
    "result_coin": 52,
    "coin_digits": 52,
    "timer": 44,
    "skill": 40,
    "fan": 40,
    "pause": 36,
    "fever": 52,
    "tsum": 32,
    "bomb": 32,
    "go": 32,
    "timeup": 40,
}
LIST_STATUS_HEADERS = {
    "game": "ゲーム\n範囲",
    "score": "スコア",
    "coin": "コイン",
    "coin_digits": "コイン\n数値",
    "result_coin": "リザルト\nコイン",
    "timer": "タイマー",
    "skill": "スキル\nボタン",
    "fan": "扇風機",
    "pause": "一時\n停止",
    "fever": "フィーバー\nゲージ",
    "tsum": "ツム",
    "bomb": "ボム",
    "go": "GO",
    "timeup": "TIME\nUP",
}

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
QPushButton#danger {
    background: #c4453c;
    font-weight: 600;
}
QPushButton#danger:hover { background: #d85a50; }
QPushButton#danger:disabled { color: #8a6e6c; background: #3a2a2a; }
QPushButton#video {
    background: #2f7fd1;
    font-weight: 600;
}
QPushButton#video:hover { background: #4590de; }
QCheckBox {
    color: #9aa3b2;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #2a303b;
    border-radius: 4px;
    background: #101216;
}
QCheckBox::indicator:checked {
    background: #5b6cff;
    border-color: #5b6cff;
}
QListWidget {
    background: #101216;
    border: 1px solid #2a303b;
    border-radius: 10px;
    padding: 4px;
    outline: none;
    font-size: 11px;
}
QListWidget::item {
    padding: 4px 8px;
    border-radius: 5px;
}
QListWidget::item:selected {
    background: #2c3344;
}
QTableWidget {
    background: #101216;
    border: 1px solid #2a303b;
    border-radius: 10px;
    outline: none;
    font-size: 12px;
    gridline-color: transparent;
}
QTableWidget::item {
    padding: 2px 1px;
}
QTableWidget::item:selected {
    background: #2c3344;
}
QHeaderView::section {
    background: #1c2028;
    color: #9aa3b2;
    border: none;
    border-bottom: 1px solid #2a303b;
    border-right: 1px solid #2a303b;
    padding: 2px 1px;
    font-size: 10px;
    font-weight: 600;
}
QHeaderView::section:hover {
    color: #e8eaed;
    background: #252a34;
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
    padding: 4px 40px 4px 8px;
    min-width: 92px;
    min-height: 36px;
}
QSpinBox::up-button, QSpinBox::down-button {
    subcontrol-origin: border;
    width: 36px;
    background: #2a303b;
    border: none;
}
QSpinBox::up-button {
    subcontrol-position: top right;
    border-top-right-radius: 6px;
}
QSpinBox::down-button {
    subcontrol-position: bottom right;
    border-bottom-right-radius: 6px;
}
QSpinBox::up-arrow, QSpinBox::down-arrow {
    width: 12px;
    height: 12px;
}
QFrame#coords {
    background: #1c2028;
    border: 1px solid #2a303b;
    border-radius: 12px;
}
QScrollArea#groupStrip {
    background: #101216;
    border: 1px solid #2a303b;
    border-radius: 10px;
}
"""


class FileListDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        if index.model() is not None and index.column() < index.model().columnCount() - 1:
            option.textElideMode = Qt.TextElideMode.ElideNone
        else:
            option.textElideMode = Qt.TextElideMode.ElideMiddle


class _GroupStripBody(QWidget):
    CELL = 80
    GAP = 6
    LABEL = 36

    pieceClicked = Signal(int)
    pieceRemoveRequested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, QColor, list[tuple[QPixmap, int]]]] = []
        self._selected: int | None = None
        self.setMouseTracking(True)

    def set_pieces(
        self,
        pixmap: QPixmap | None,
        pieces: list[dict[str, int]],
        selected: int | None = None,
    ) -> None:
        self._rows = []
        self._selected = selected
        if pixmap is None or pixmap.isNull() or not pieces:
            self.updateGeometry()
            self.update()
            self.setMinimumHeight(0)
            return
        grouped: dict[str, list[tuple[QPixmap, int]]] = {}
        for index, piece in enumerate(pieces):
            key = "B" if piece.get("kind") == "bomb" else str(int(piece.get("group") or 1))
            grouped.setdefault(key, []).append((self._crop(pixmap, piece), index))

        def sort_key(key: str) -> tuple[int, int]:
            if key == "B":
                return (1, 0)
            return (0, int(key))

        for key in sorted(grouped, key=sort_key):
            color = QColor("#FF5C5C") if key == "B" else QColor(tsum_group_color(int(key)))
            self._rows.append((key, color, grouped[key]))
        self.setMinimumHeight(self.heightForWidth(max(self.width(), 1)))
        self.updateGeometry()
        self.update()

    def _crop(self, pixmap: QPixmap, piece: dict[str, int]) -> QPixmap:
        x, y, radius = int(piece["x"]), int(piece["y"]), max(8, int(piece.get("r") or 16))
        span = max(12, int(round(radius * 1.05)))
        tile = pixmap.copy(QRect(x - span, y - span, span * 2, span * 2))
        return tile.scaled(
            self.CELL,
            self.CELL,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._needed_height(width)

    def sizeHint(self) -> QSize:
        return QSize(480, self._needed_height(max(self.width(), 480)))

    def minimumSizeHint(self) -> QSize:
        if not self._rows:
            return QSize(0, 0)
        return QSize(self.LABEL + self.CELL, self.CELL)

    def _per_row(self, width: int) -> int:
        inner = max(self.CELL, width - self.LABEL - 8)
        return max(1, (inner + self.GAP) // (self.CELL + self.GAP))

    def _needed_height(self, width: int) -> int:
        if not self._rows:
            return 0
        per = self._per_row(width)
        lines = 0
        for _key, _color, tiles in self._rows:
            lines += max(1, (len(tiles) + per - 1) // per)
        return lines * (self.CELL + self.GAP) + self.GAP

    def _hit(self, pos) -> int | None:
        for rect, index, _key, _color, _tile in self._iter_tiles(max(self.width(), 1)):
            if rect.contains(pos):
                return index
        return None

    def _iter_tiles(self, width: int):
        per = self._per_row(width)
        y = self.GAP
        for key, color, tiles in self._rows:
            for start in range(0, len(tiles), per):
                chunk = tiles[start : start + per]
                x = self.LABEL
                for tile, index in chunk:
                    yield QRect(x, y, self.CELL, self.CELL), index, key, color, tile
                    x += self.CELL + self.GAP
                y += self.CELL + self.GAP

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.setMinimumHeight(self.heightForWidth(max(self.width(), 1)))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        hit = self._hit(event.position().toPoint())
        if hit is None:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.pieceRemoveRequested.emit(hit)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._selected = hit
            self.update()
            self.pieceClicked.emit(hit)
            event.accept()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101216"))
        if not self._rows:
            return
        painter.setFont(QFont("Yu Gothic UI", 16, QFont.Weight.DemiBold))
        width = max(self.width(), 1)
        per = self._per_row(width)
        y = self.GAP
        for key, color, tiles in self._rows:
            for start in range(0, len(tiles), per):
                chunk = tiles[start : start + per]
                if start == 0:
                    painter.setPen(color)
                    painter.drawText(
                        QRect(2, y, self.LABEL - 2, self.CELL),
                        Qt.AlignmentFlag.AlignCenter,
                        key,
                    )
                x = self.LABEL
                for tile, index in chunk:
                    painter.drawPixmap(x, y, tile)
                    selected = index == self._selected
                    painter.setPen(QPen(QColor(255, 255, 255) if selected else color, 3 if selected else 2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(x, y, self.CELL - 1, self.CELL - 1)
                    x += self.CELL + self.GAP
                y += self.CELL + self.GAP


class GroupStrip(QScrollArea):
    pieceClicked = Signal(int)
    pieceRemoveRequested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("groupStrip")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body = _GroupStripBody()
        self._body.pieceClicked.connect(self.pieceClicked.emit)
        self._body.pieceRemoveRequested.connect(self.pieceRemoveRequested.emit)
        self.setWidget(self._body)

    def set_pieces(
        self,
        pixmap: QPixmap | None,
        pieces: list[dict[str, int]],
        selected: int | None = None,
    ) -> None:
        self._body.set_pieces(pixmap, pieces, selected=selected)

    def selected_index(self) -> int | None:
        return self._body._selected


class GroupListWindow(QDialog):
    pieceClicked = Signal(int)
    pieceRemoveRequested = Signal(int)
    groupChanged = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("羅列")
        self.setModal(False)
        self.setStyleSheet(STYLESHEET)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self._pieces: list[dict[str, int]] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("ツム種類"))
        self.group_label = QLabel("No.  1")
        bar.addWidget(self.group_label)
        self.group_down_btn = QPushButton("－")
        self.group_up_btn = QPushButton("＋")
        self.group_down_btn.setEnabled(False)
        self.group_up_btn.setEnabled(False)
        bar.addWidget(self.group_down_btn)
        bar.addWidget(self.group_up_btn)
        self.delete_btn = QPushButton("消す")
        self.delete_btn.setEnabled(False)
        bar.addWidget(self.delete_btn)
        bar.addStretch(1)
        self.close_btn = QPushButton("閉じる")
        bar.addWidget(self.close_btn)
        layout.addLayout(bar)
        self.strip = GroupStrip()
        layout.addWidget(self.strip, 1)
        self.strip.pieceClicked.connect(self._on_piece_clicked)
        self.strip.pieceRemoveRequested.connect(self.pieceRemoveRequested.emit)
        self.group_down_btn.clicked.connect(self._nudge_group_down)
        self.group_up_btn.clicked.connect(self._nudge_group_up)
        self.delete_btn.clicked.connect(self._on_delete)
        self.close_btn.clicked.connect(self.close)

    def set_pieces(
        self,
        pixmap: QPixmap | None,
        pieces: list[dict[str, int]],
        selected: int | None = None,
    ) -> None:
        self._pieces = pieces
        self.strip.set_pieces(pixmap, pieces, selected=selected)
        self._sync_bar(selected)

    def _sync_bar(self, selected: int | None) -> None:
        piece = None
        if selected is not None and 0 <= selected < len(self._pieces):
            piece = self._pieces[selected]
        self.delete_btn.setEnabled(piece is not None)
        is_tsum = piece is not None and piece.get("kind") == "tsum"
        if is_tsum and piece is not None:
            group = int(piece.get("group") or 1)
            self.group_label.setText(f"No.  {group}")
            self.group_down_btn.setEnabled(group > 1)
            self.group_up_btn.setEnabled(group < 12)
        else:
            self.group_down_btn.setEnabled(False)
            self.group_up_btn.setEnabled(False)

    def _current_group(self) -> int:
        selected = self.strip.selected_index()
        if selected is None or selected >= len(self._pieces):
            return 1
        piece = self._pieces[selected]
        if piece.get("kind") != "tsum":
            return 1
        return int(piece.get("group") or 1)

    def _nudge_group_down(self) -> None:
        group = self._current_group()
        if group > 1:
            self.groupChanged.emit(group - 1)

    def _nudge_group_up(self) -> None:
        group = self._current_group()
        if group < 12:
            self.groupChanged.emit(group + 1)

    def _on_piece_clicked(self, index: int) -> None:
        self._sync_bar(index)
        self.pieceClicked.emit(index)

    def _on_delete(self) -> None:
        selected = self.strip.selected_index()
        if selected is None:
            return
        self.pieceRemoveRequested.emit(selected)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        selected = self.strip.selected_index()
        if selected is not None and key in (Qt.Key.Key_Backspace, Qt.Key.Key_X):
            self.pieceRemoveRequested.emit(selected)
            event.accept()
            return
        if self.group_up_btn.isEnabled() or self.group_down_btn.isEnabled():
            if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
                self.groupChanged.emit(key - Qt.Key.Key_1 + 1)
                event.accept()
                return
        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ツムツム ゲーム範囲トレーナー")
        icon = self._ensure_app_icon()
        if icon is not None:
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(1280, 840)
        self.setMinimumSize(980, 640)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLESHEET)

        self.dataset = Dataset(DATA_DIR)
        self.predictor = Predictor(self.dataset.models_dir)
        self.current_id: str | None = None
        self._active_key = "game"
        self.train_worker: TrainWorker | None = None
        self._train_started_at: float | None = None
        self._cuda_ready: bool | None = None
        self._dirty = False
        self._shutdown_after_train = False
        self._awake_timer: QTimer | None = None
        self._switching = False
        self._extractor_process = None
        self._ipc_buffers: dict[int, bytes] = {}
        self._last_boxes: dict[str, dict[str, int]] = {}
        self._last_piece_radius: dict[str, int] = {}
        self._list_sort_key: str | None = None
        self._list_sort_asc = True
        self._skill_registered: dict[str, str] = {}
        self._settings = QSettings("workshop", "TsumTsumScreenTrainer")
        self._group_window: GroupListWindow | None = None
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
        self.hint_label = QLabel("画像をドロップ / Ctrl+V / 「画像を開く」。左で種類にチェックを付けて保存します。")
        self.hint_label.setObjectName("hint")
        self.hint_label.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(self.hint_label)
        top_layout.addLayout(title_box, 1)

        self.open_btn = QPushButton("画像を開く")
        self.paste_btn = QPushButton("貼り付け")
        self.confirm_btn = QPushButton("この範囲を保存")
        self.confirm_btn.setObjectName("accent")
        self.skip_btn = QPushButton("使わない")
        self.next_btn = QPushButton("次へ")
        self.prev_btn = QPushButton("前へ")
        self.clear_btn = QPushButton("この場所を消す")
        self.undo_piece_btn = QPushButton("1つ戻す")
        self.predict_btn = QPushButton("この画像を予測")
        self.train_btn = QPushButton("学習する")
        self.train_btn.setObjectName("primary")
        self.train_shutdown_btn = QPushButton("学習してシャットダウン")
        for button in (
            self.open_btn,
            self.paste_btn,
            self.confirm_btn,
            self.skip_btn,
            self.prev_btn,
            self.next_btn,
            self.clear_btn,
            self.undo_piece_btn,
            self.predict_btn,
            self.train_btn,
            self.train_shutdown_btn,
        ):
            top_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QFrame()
        left.setObjectName("sidebar")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.addWidget(QLabel("教える場所"))
        place_hint = QLabel("チェックした種類を保存・学習します")
        place_hint.setObjectName("hint")
        left_layout.addWidget(place_hint)
        self.region_list = QListWidget()
        self.region_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.region_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.region_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for key, label, color in PLACE_SPECS:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setForeground(QColor(color))
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            item.setCheckState(Qt.CheckState.Unchecked)
            self.region_list.addItem(item)
        self.region_list.setCurrentRow(0)
        first = self.region_list.item(0)
        if first is not None:
            first.setCheckState(Qt.CheckState.Checked)
        self._fit_region_list()
        left_layout.addWidget(self.region_list)
        self.read_coin_btn = QPushButton("コインの数字を取る")
        left_layout.addWidget(self.read_coin_btn)
        self.open_result_train_btn = QPushButton("resultの学習画像を開く")
        left_layout.addWidget(self.open_result_train_btn)
        self.model_label = QLabel()
        self.model_label.setObjectName("hint")
        self.model_label.setWordWrap(True)
        left_layout.addWidget(self.model_label)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        left_layout.addWidget(self.progress)
        left_layout.addStretch(1)
        self.copy_data_btn = QPushButton("DATAをアップ")
        self.import_data_btn = QPushButton("DATA DOWNLOAD")
        self.server_save_btn = QPushButton("サーバーに保存")
        self.server_load_btn = QPushButton("サーバーから開く")
        self.server_settings_btn = QPushButton("サーバー接続")
        self.shortcut_btn = QPushButton("起動アイコン作成")
        left_grid = QGridLayout()
        left_grid.setContentsMargins(0, 0, 0, 0)
        left_buttons = (
            self.copy_data_btn,
            self.import_data_btn,
            self.server_save_btn,
            self.server_load_btn,
            self.server_settings_btn,
            self.shortcut_btn,
        )
        for i, button in enumerate(left_buttons):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            left_grid.addWidget(button, i // 2, i % 2)
        for col in range(2):
            left_grid.setColumnStretch(col, 1)
        left_layout.addLayout(left_grid)
        left.setMinimumWidth(317)
        left.setMaximumWidth(461)

        self.canvas = ImageCanvas()
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._canvas_host = QWidget()
        canvas_host_layout = QVBoxLayout(self._canvas_host)
        canvas_host_layout.setContentsMargins(0, 0, 0, 0)
        canvas_host_layout.setSpacing(0)
        canvas_host_layout.addWidget(self.canvas)
        self._canvas_host.installEventFilter(self)
        self._toast = QLabel(self.canvas)
        self._toast.setObjectName("toast")
        self._toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._toast.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_save_toast)
        self._train_fx = TrainEffect(root)

        right = QFrame()
        right.setObjectName("sidebar")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.addWidget(QLabel("画像ファイル"))
        self.stats_label = QLabel()
        self.stats_label.setObjectName("hint")
        self.stats_label.setWordWrap(True)
        right_layout.addWidget(self.stats_label)
        self.stats_grid = QGridLayout()
        self.stats_grid.setContentsMargins(0, 0, 0, 0)
        self.stats_grid.setHorizontalSpacing(8)
        self.stats_grid.setVerticalSpacing(0)
        self._stats_names: list[QLabel] = []
        self._stats_values: list[QLabel] = []
        for index in range(12):
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 8, 0)
            cell_layout.setSpacing(4)
            name = QLabel()
            name.setObjectName("hint")
            value = QLabel()
            value.setObjectName("hint")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cell_layout.addWidget(name, 1)
            cell_layout.addWidget(value)
            self._stats_names.append(name)
            self._stats_values.append(value)
            self.stats_grid.addWidget(cell, index // 6, index % 6)
        for col in range(6):
            self.stats_grid.setColumnStretch(col, 1)
        right_layout.addLayout(self.stats_grid)
        self.stats_hint = QLabel()
        self.stats_hint.setObjectName("hint")
        self.stats_hint.setWordWrap(True)
        right_layout.addWidget(self.stats_hint)
        unused_row = QHBoxLayout()
        self.show_unused_chk = QCheckBox("使わない画像も見る")
        self.delete_unused_one_btn = QPushButton("この画像を消す")
        self.delete_unused_btn = QPushButton("使わない画像を全部消す")
        unused_row.addWidget(self.show_unused_chk, 1)
        unused_row.addWidget(self.delete_unused_one_btn)
        unused_row.addWidget(self.delete_unused_btn)
        right_layout.addLayout(unused_row)
        self.list_widget = QTableWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.list_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setWordWrap(False)
        self.list_widget.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.list_widget.setItemDelegate(FileListDelegate(self.list_widget))
        self.list_widget.setAutoScroll(False)
        self.list_widget.setShowGrid(False)
        self.list_widget.verticalHeader().setVisible(False)
        self.list_widget.verticalHeader().setDefaultSectionSize(28)
        header = self.list_widget.horizontalHeader()
        header.setHighlightSections(False)
        header.setStretchLastSection(True)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)
        header.setMinimumSectionSize(28)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setFixedHeight(36)
        header.sectionClicked.connect(self.on_list_header_clicked)
        self._sync_list_columns()
        right_layout.addWidget(self.list_widget, 1)
        self.delete_btn = QPushButton("選択を削除")
        self.delete_btn.setObjectName("danger")
        self.skill_register_btn = QPushButton("SKILL画像として登録")
        self.video_app_btn = QPushButton("動画編集・生成")
        self.video_app_btn.setObjectName("video")
        stay_row = QHBoxLayout()
        stay_row.setContentsMargins(0, 0, 0, 0)
        stay_row.addWidget(self.delete_btn)
        stay_row.addWidget(self.skill_register_btn)
        stay_row.addWidget(self.video_app_btn)
        right_layout.addLayout(stay_row)
        right.setMinimumWidth(480)

        self._body_split = splitter
        splitter.addWidget(left)
        splitter.addWidget(self._canvas_host)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([346, 860, 720])
        layout.addWidget(splitter, 1)

        coords = QFrame()
        coords.setObjectName("coords")
        coords_layout = QHBoxLayout(coords)
        coords_layout.setContentsMargins(12, 8, 12, 8)
        self.reuse_btn = QPushButton("同じ枠を使う")
        coords_layout.addWidget(self.reuse_btn)
        self.copy_box_btn = QPushButton("この枠をコピー")
        coords_layout.addWidget(self.copy_box_btn)
        coords_layout.addWidget(QLabel("ツム種類"))
        self.spin_group = QSpinBox()
        self.spin_group.setPrefix("No.  ")
        self.spin_group.setRange(1, 12)
        self.spin_group.setValue(1)
        coords_layout.addWidget(self.spin_group)
        self.piece_count_label = QLabel()
        self.piece_count_label.setObjectName("hint")
        self.piece_count_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        coords_layout.addWidget(self.piece_count_label, 1)
        self.trace_chain_btns: list[QPushButton] = []
        for index in range(3):
            button = QPushButton("なぞる")
            button.setEnabled(False)
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            coords_layout.addWidget(button)
            self.trace_chain_btns.append(button)
        self.list_groups_btn = QPushButton("羅列")
        self.list_groups_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.list_groups_btn.setMinimumWidth(self.trace_chain_btns[0].sizeHint().width())
        coords_layout.addWidget(self.list_groups_btn)
        self.coords_hint = QLabel("上下キーで画像を切替  /  左右キーで枠を1px  /  Shift+矢印で10px  /  Ctrl+矢印でサイズ")
        self.coords_hint.setObjectName("hint")
        self.coords_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
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
        self.undo_piece_btn.clicked.connect(self.undo_last_piece)
        self.reuse_btn.clicked.connect(self.reuse_last_box)
        self.copy_box_btn.clicked.connect(self.copy_current_box)
        self.read_coin_btn.clicked.connect(self.read_coin_number)
        self.open_result_train_btn.clicked.connect(self.open_result_train_images)
        self.predict_btn.clicked.connect(self.predict_current)
        self.train_btn.clicked.connect(self.on_train_button)
        self.train_shutdown_btn.clicked.connect(self.on_train_shutdown_button)
        self._train_fx.cancelRequested.connect(self.cancel_training)
        self._train_fx.shutdownToggleRequested.connect(self.on_train_shutdown_button)
        self.delete_btn.clicked.connect(self.delete_current)
        self.skill_register_btn.clicked.connect(self.register_skill_image)
        self.delete_unused_one_btn.clicked.connect(self.delete_current)
        self.delete_unused_btn.clicked.connect(self.delete_unused_images)
        self.show_unused_chk.toggled.connect(self.on_show_unused_toggled)
        self.copy_data_btn.clicked.connect(self.copy_data_folder)
        self.import_data_btn.clicked.connect(self.import_data_folder)
        self.server_save_btn.clicked.connect(self.upload_data_to_server)
        self.server_load_btn.clicked.connect(self.download_data_from_server)
        self.server_settings_btn.clicked.connect(self.edit_server_settings)
        self.shortcut_btn.clicked.connect(self.create_launch_shortcut)
        self.video_app_btn.clicked.connect(self.launch_video_extractor)
        self.list_widget.currentCellChanged.connect(self.on_list_cell_changed)
        self.region_list.currentItemChanged.connect(self.on_region_type_changed)
        self.region_list.itemChanged.connect(self.on_place_item_changed)
        self.canvas.regionCommitted.connect(self.on_region_committed)
        self.canvas.regionChanged.connect(self.on_region_changed)
        self.canvas.piecesChanged.connect(self.on_pieces_changed)
        self.canvas.pieceGroupChanged.connect(self.on_piece_group_changed)
        self.canvas.filesDropped.connect(self.import_paths)
        self.canvas.imageDropped.connect(self.import_qimage)
        self.canvas.installEventFilter(self)
        self.spin_group.valueChanged.connect(self.on_group_changed)
        for index, button in enumerate(self.trace_chain_btns):
            button.clicked.connect(lambda _checked=False, i=index: self.trace_chain_candidate(i))
        self.list_groups_btn.clicked.connect(self.open_group_list)
        QTimer.singleShot(0, self._sync_canvas_3_2)

    def _bind_shortcuts(self) -> None:
        QShortcut(QKeySequence.StandardKey.Undo, self, self.undo_last_piece)
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
        self._ipc_server = QLocalServer(self)
        self._ipc_server.newConnection.connect(self._on_ipc_connection)
        if self._ipc_server.listen(IPC_NAME):
            return
        QLocalServer.removeServer(IPC_NAME)
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
            action = str(payload.get("action") or "")
        except Exception:
            sock.write(b'{"ok":false}\n')
            sock.flush()
            return
        sock.write(b'{"ok":true}\n')
        sock.flush()
        if action == "release-data":
            if not self._is_training():
                try:
                    self.predictor.release()
                except Exception:
                    pass
            return
        if action == "reload-data":
            self._reload_after_data_import()
            return
        if paths:
            self.import_incoming_paths(paths)
        else:
            self._bring_to_front()

    def import_incoming_paths(self, paths: list[str]) -> None:
        self._bring_to_front()
        self.import_paths(paths)

    def _bring_to_front(self) -> None:
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def _visible_samples(self) -> list[Sample]:
        samples = self.dataset.all()
        if self.show_unused_chk.isChecked():
            return samples
        return [sample for sample in samples if sample.status != "skipped"]

    def _coin_digits_of(self, sample: Sample) -> str:
        for box_key in COIN_BOX_KEYS:
            digits = "".join(char for char in (sample.readings or {}).get(box_key, "") if char.isdigit())
            if digits:
                return digits
        return ""

    def _sample_sort_value(self, sample: Sample, key: str):
        if key == "file":
            return (sample.source_name.casefold(), sample.id)
        if key == "coin_digits":
            digits = self._coin_digits_of(sample)
            if not digits:
                return (1, 0, sample.id)
            return (0, int(digits), sample.id)
        state = self._key_list_state(sample, key)
        rank = {"confirmed": 0, "predicted": 1}.get(state, 2)
        return (rank, sample.source_name.casefold(), sample.id)

    def _ordered_visible_samples(self) -> list[Sample]:
        samples = self._visible_samples()
        key = self._list_sort_key
        if not key:
            return list(reversed(samples))
        return sorted(
            samples,
            key=lambda sample: self._sample_sort_value(sample, key),
            reverse=not self._list_sort_asc,
        )

    def _neighbor_list_id(self, removed_id: str) -> str | None:
        ids = [sample.id for sample in self._ordered_visible_samples()]
        if removed_id not in ids:
            return ids[0] if ids else None
        index = ids.index(removed_id)
        if index + 1 < len(ids):
            return ids[index + 1]
        if index > 0:
            return ids[index - 1]
        return None

    def on_list_header_clicked(self, section: int) -> None:
        keys = self._list_status_keys() + ["file"]
        if section < 0 or section >= len(keys):
            return
        key = keys[section]
        if self._list_sort_key == key:
            self._list_sort_asc = not self._list_sort_asc
        else:
            self._list_sort_key = key
            self._list_sort_asc = True
        self.refresh_list(self.current_id)

    def refresh_list(self, select_id: str | None = None) -> None:
        self._skill_registered = registered_skills_by_sample()
        self._sync_list_columns()
        selected = select_id or self.current_id
        samples = self._ordered_visible_samples()
        scroll = self.list_widget.verticalScrollBar().value()
        prev_current = self._list_id_at(self.list_widget.currentRow())
        existing = [self._list_id_at(row) for row in range(self.list_widget.rowCount())]
        new_ids = [sample.id for sample in samples]
        self.list_widget.blockSignals(True)
        if existing != new_ids:
            self.list_widget.setRowCount(len(samples))
        for row, sample in enumerate(samples):
            self._style_list_row(row, sample)
        moved_row = None
        if selected and selected != prev_current:
            for row in range(self.list_widget.rowCount()):
                if self._list_id_at(row) == selected:
                    self.list_widget.setCurrentCell(row, 0)
                    moved_row = row
                    break
        elif selected is None and self.list_widget.rowCount() and prev_current is None:
            self.list_widget.setCurrentCell(0, 0)
            moved_row = 0
        elif selected and selected == prev_current:
            for row in range(self.list_widget.rowCount()):
                if self._list_id_at(row) == selected:
                    self.list_widget.setCurrentCell(row, 0)
                    break
        self.list_widget.blockSignals(False)
        if moved_row is None:
            self.list_widget.verticalScrollBar().setValue(scroll)
        else:
            item = self.list_widget.item(moved_row, 0)
            if item is not None:
                self.list_widget.scrollToItem(item)
        self.update_stats()

    def _list_id_at(self, row: int) -> str | None:
        if row < 0:
            return None
        item = self.list_widget.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _style_list_row(self, row: int, sample: Sample) -> None:
        skipped = sample.status == "skipped"
        status_keys = self._list_status_keys()
        for col, key in enumerate(status_keys):
            if key == "coin_digits":
                digits = ""
                for box_key in COIN_BOX_KEYS:
                    digits = "".join(char for char in (sample.readings or {}).get(box_key, "") if char.isdigit())
                    if digits:
                        break
                if digits:
                    text, color = format_coin_number(digits), QColor("#3DDC97")
                else:
                    text, color = "未", QColor("#8b93a0")
            else:
                state = self._key_list_state(sample, key)
                if state == "confirmed":
                    text, color = "済", QColor("#3DDC97")
                elif state == "predicted":
                    text, color = "予測", QColor("#FFB020")
                else:
                    text, color = "未", QColor("#8b93a0")
            if skipped:
                color = QColor("#7a8190")
            item = self.list_widget.item(row, col)
            if item is None:
                item = QTableWidgetItem()
                self.list_widget.setItem(row, col, item)
            item.setText(text)
            item.setForeground(color)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setData(Qt.ItemDataRole.UserRole, sample.id)
            item.setFlags((item.flags() | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled) & ~Qt.ItemFlag.ItemIsEditable)
        name_col = len(status_keys)
        name_item = self.list_widget.item(row, name_col)
        if name_item is None:
            name_item = QTableWidgetItem()
            self.list_widget.setItem(row, name_col, name_item)
        name = sample.source_name
        skill_name = self._skill_registered.get(sample.id, "")
        if skill_name:
            name = f"SKILL  {skill_name}  {name}"
        elif skipped:
            name = f"使わない  {name}"
        name_item.setText(name)
        if skipped and not skill_name:
            name_item.setForeground(QColor("#7a8190"))
        elif skill_name:
            name_item.setForeground(QColor("#3DDC97"))
        else:
            name_item.setForeground(QColor("#c5cad3"))
        name_item.setData(Qt.ItemDataRole.UserRole, sample.id)
        name_item.setFlags(
            (name_item.flags() | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            & ~Qt.ItemFlag.ItemIsEditable
        )
        name_item.setToolTip(sample.source_name)

    def _sample_has_active(self, sample: Sample) -> bool:
        if is_piece_key(self._active_key):
            return self._active_key in sample.confirmed and any(
                piece.get("kind") == self._active_key for piece in sample.pieces
            )
        return self._active_key in sample.confirmed

    def _key_list_state(self, sample: Sample, key: str) -> str:
        if is_scene_key(key):
            return "confirmed" if key in sample.confirmed else "empty"
        if is_piece_key(key):
            has = any(piece.get("kind") == key for piece in sample.pieces)
        else:
            has = key in sample.regions
        if has and key in sample.confirmed:
            return "confirmed"
        if has:
            return "predicted"
        return "empty"

    def update_stats(self) -> None:
        counts = self.dataset.counts()
        labeled_counts = self.dataset.labeled_counts()
        keys = [*REGION_KEYS, *PIECE_KEYS, "coin_digits"]
        for name, value, key in zip(self._stats_names, self._stats_values, keys):
            name.setText(LIST_STATUS_HEADERS.get(key, PLACE_LABELS.get(key, key)).replace("\n", ""))
            value.setText(str(labeled_counts.get(key, 0)))
        self.stats_label.setText(
            f"全 {counts['total']} 枚\n"
            f"保存済み {counts['labeled']} / 予測 {counts['predicted']} / 未設定 {counts['unlabeled']} / 使わない {counts['skipped']}"
        )
        self.stats_hint.setText(
            f"学習の目安: 種類ごとに {MIN_TRAIN_SAMPLES} 枚以上。コインの数字も同じです。"
        )
        ready = self.predictor.ready_keys()
        if ready:
            names = "、".join(PLACE_LABELS.get(key, key) for key in ready)
            self.model_label.setText(f"モデル: {names}。新しい画像には自動で予測します。")
        else:
            self.model_label.setText("モデル: まだありません。範囲を教えてから学習してください。")
        self.train_btn.setEnabled(bool(self._trainable_jobs()) and self.train_worker is None)
        if self._is_training():
            self._lock_for_training()
            return
        self.train_btn.setText("学習する")
        self._sync_train_shutdown_btn()
        has_sample = self.current_id is not None
        has_active = any(self._key_has_content(key) for key in self._selected_place_keys())
        self.confirm_btn.setEnabled(has_sample and has_active)
        self.confirm_btn.setText(self._confirm_btn_label())
        self.skip_btn.setEnabled(has_sample)
        self.next_btn.setEnabled(has_sample and self._unlabeled_id(self.current_id) is not None)
        self.prev_btn.setEnabled(has_sample and self._unlabeled_id(self.current_id, backward=True) is not None)
        self.clear_btn.setEnabled(has_sample and has_active)
        self.clear_btn.setText(f"{PLACE_LABELS.get(self._active_key, '範囲')}を消す")
        piece_mode = is_piece_key(self._active_key)
        scene_mode = is_scene_key(self._active_key)
        self.undo_piece_btn.setEnabled(
            has_sample and piece_mode and self.canvas.has_piece_of_kind(self._active_key)
        )
        self.spin_group.setEnabled(self._active_key == "tsum")
        has_last = (
            self._active_key in self._last_piece_radius
            if piece_mode
            else self._active_key in self._last_boxes
        )
        self.reuse_btn.setEnabled(has_sample and has_last and not scene_mode)
        name = PLACE_LABELS.get(self._active_key, "範囲")
        self.reuse_btn.setText(f"{name}の大きさを使う" if piece_mode else f"{name}の枠を使う")
        has_box = has_sample and not piece_mode and not scene_mode and self._active_key in self.canvas.all_region_boxes()
        self.copy_box_btn.setEnabled(has_box)
        self.copy_box_btn.setText(f"{name}をコピー")
        counts_map = self.canvas.piece_counts()
        parts = [f"{k} {v}" for k, v in counts_map.items()]
        candidates = self.canvas.chain_candidates()
        if candidates:
            parts.append("チェーン " + " / ".join(str(len(path)) for path in candidates))
        self.piece_count_label.setText("  ".join(parts))
        for index, button in enumerate(self.trace_chain_btns):
            if index < len(candidates) and len(candidates[index]) >= 2:
                button.setText(f"なぞる {len(candidates[index])}")
                button.setEnabled(True)
            else:
                button.setText("なぞる")
                button.setEnabled(False)
        self.predict_btn.setEnabled(has_sample and self.predictor.is_ready())
        self.read_coin_btn.setEnabled(
            has_sample and any(key in self.canvas.all_region_boxes() for key in COIN_BOX_KEYS)
        )
        self.open_result_train_btn.setEnabled(True)
        self.delete_btn.setEnabled(has_sample)
        if hasattr(self, "skill_register_btn"):
            self.skill_register_btn.setEnabled(has_sample)
            skill_name = self._skill_registered.get(self.current_id or "", "")
            if skill_name:
                self.skill_register_btn.setText(f"SKILL登録済み（{skill_name}）")
            else:
                self.skill_register_btn.setText("SKILL画像として登録")
        self._update_unused_delete_buttons()

    def on_list_cell_changed(
        self, current_row: int, _current_col: int, previous_row: int, _previous_col: int
    ) -> None:
        if self._switching or current_row == previous_row:
            return
        if not self._confirm_discard():
            self._switching = True
            self.list_widget.setCurrentCell(max(previous_row, 0), 0)
            self._switching = False
            return
        sample_id = self._list_id_at(current_row)
        if sample_id is None:
            self.current_id = None
            self.canvas.clear_image()
            self._set_dirty(False)
            self._refresh_region_list()
            self.update_stats()
            return
        self.show_sample(sample_id)

    def on_place_item_changed(self, _item: QListWidgetItem) -> None:
        if self.region_list.signalsBlocked():
            return
        self._apply_visible_keys()
        self.refresh_list(select_id=self.current_id)
        self.update_stats()

    def on_region_type_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        key = current.data(Qt.ItemDataRole.UserRole)
        if not key:
            return
        self._active_key = key
        self.canvas.set_active_key(key)
        if current.checkState() != Qt.CheckState.Checked:
            self.region_list.blockSignals(True)
            current.setCheckState(Qt.CheckState.Checked)
            self.region_list.blockSignals(False)
        self._apply_visible_keys()
        self._refresh_region_list()
        self.refresh_list(select_id=self.current_id)
        self._apply_sample_hint()

    def _refresh_region_list(self) -> None:
        self.region_list.blockSignals(True)
        current_item = None
        for row in range(self.region_list.count()):
            item = self.region_list.item(row)
            key = item.data(Qt.ItemDataRole.UserRole)
            item.setText(PLACE_LABELS.get(key, key))
            if key == self._active_key:
                current_item = item
        if current_item is not None:
            self.region_list.setCurrentItem(current_item)
        self.region_list.blockSignals(False)
        self._fit_region_list()

    def _fit_region_list(self) -> None:
        rows = self.region_list.count()
        if rows <= 0:
            return
        row_h = self.region_list.sizeHintForRow(0)
        if row_h <= 0:
            row_h = 28
        frame = self.region_list.frameWidth() * 2
        self.region_list.setFixedHeight(rows * row_h + frame + 12)

    def show_sample(self, sample_id: str) -> None:
        sample = self.dataset.get(sample_id)
        if sample is None:
            return
        selected = set(self._selected_place_keys())
        if self.predictor.piece_model is not None and any(key in selected for key in PIECE_KEYS):
            if any(key in selected and key not in sample.confirmed for key in PIECE_KEYS):
                try:
                    self._predict_into_sample(sample, overwrite=True)
                except Exception:
                    pass
                sample = self.dataset.get(sample_id) or sample
            elif "tsum" in selected and any(piece.get("kind") == "tsum" for piece in sample.pieces):
                try:
                    self._relabel_tsum_groups(sample)
                except Exception:
                    pass
                sample = self.dataset.get(sample_id) or sample
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
        self._apply_visible_keys()
        self._set_dirty(False)
        self._refresh_region_list()
        self._apply_sample_hint(sample)
        self._refresh_group_strip()
        self.update_stats()

    def _apply_sample_hint(self, sample: Sample | None = None) -> None:
        if sample is None and self.current_id:
            sample = self.dataset.get(self.current_id)
        if sample is None:
            return
        if is_scene_key(self._active_key):
            name = PLACE_LABELS.get(self._active_key, "画面")
            if self._active_key in sample.confirmed:
                self.hint_label.setText(f"この画像は「{name}」として保存済みです。")
            elif self.predictor.scene_model is None:
                self.hint_label.setText(f"この画像が「{name}」なら保存してください。枠は不要です。")
            else:
                try:
                    kind, score = self.predictor.predict_scene(sample.image_path)
                except Exception:
                    kind, score = "other", 0.0
                    self.hint_label.setText(f"この画像が「{name}」なら保存してください。枠は不要です。")
                    kind = None
                if kind is not None:
                    if kind == self._active_key:
                        self.hint_label.setText(
                            f"予測は「{PLACE_LABELS.get(kind, kind)}」({score:.0%}) です。合っていれば保存してください。"
                        )
                    elif kind != "other":
                        self.hint_label.setText(
                            f"予測は「{PLACE_LABELS.get(kind, kind)}」({score:.0%}) です。違うなら「{name}」を保存してください。"
                        )
                    else:
                        self.hint_label.setText(
                            f"予測では GO / TIME UP ではありません。この画像が「{name}」なら保存してください。"
                        )
            self._append_skill_registered_hint(sample)
            return
        if sample.status == "unlabeled":
            self.hint_label.setText("左のチェックを付けた種類だけ保存します。名前をクリックすると、その枠を直せます。")
        elif sample.status == "predicted":
            self.hint_label.setText("オレンジはゲーム範囲の予測です。他の場所も左から選んで囲めます。保存するか、使わないなら「使わない」。")
        elif sample.status == "skipped":
            self.hint_label.setText("この画像は使わない設定です。囲んで保存すれば学習に使えます。")
        else:
            self.hint_label.setText("色つきの四角が付いています。保存したい種類にチェックを付けて保存してください。")
        self._append_skill_registered_hint(sample)

    def _append_skill_registered_hint(self, sample: Sample) -> None:
        skill_name = self._skill_registered.get(sample.id, "")
        if not skill_name:
            return
        extra = f"この画像は {skill_name} のスキル画像として登録済みです。"
        current = self.hint_label.text()
        if extra in current:
            return
        self.hint_label.setText(f"{current}\n{extra}" if current else extra)

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
            self._set_dirty(self._active_needs_save())
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
        self._set_dirty(self._active_needs_save())
        self._refresh_region_list()
        self.statusBar().showMessage(
            f"「{name}」の前の枠を載せました。位置を直して保存してください",
            4000,
        )

    def copy_current_box(self) -> None:
        if self._block_if_training() or not self.current_id:
            return
        if is_piece_key(self._active_key) or is_scene_key(self._active_key):
            return
        key = self._active_key
        name = PLACE_LABELS.get(key, "範囲")
        box = self.canvas.all_region_boxes().get(key)
        if box is None:
            QMessageBox.information(self, "枠がありません", f"先に「{name}」を囲んでください。")
            return
        self._last_boxes[key] = dict(box)
        self.update_stats()
        self.statusBar().showMessage(
            f"「{name}」の枠をコピーしました。次の画像で「{name}の枠を使う」を押してください",
            5000,
        )

    def launch_video_extractor(self) -> None:
        if self._activate_extractor():
            QMessageBox.information(
                self,
                "すでに起動しています",
                "動画フレーム抜き出しは、すでに開いています。",
            )
            return
        if self._extractor_process is not None and self._extractor_process.poll() is None:
            QMessageBox.information(
                self,
                "すでに起動しています",
                "動画フレーム抜き出しは、すでに起動しています。",
            )
            return
        script = VIDEO_EXTRACTOR_MAIN
        if not script.exists():
            QMessageBox.warning(
                self,
                "アプリが見つかりません",
                f"動画抜き出しアプリが見つかりません。\n{script}",
            )
            return
        kwargs: dict = {
            "cwd": str(script.parent),
            "env": self._subprocess_env(),
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            self._extractor_process = subprocess.Popen(
                [str(self._resolve_launch_python()), str(script)],
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "起動に失敗", str(exc))
            return
        dialog = QProgressDialog("動画フレーム抜き出しを起動しています…", None, 0, 0, self)
        dialog.setWindowTitle("起動中")
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.show()
        QApplication.processEvents()
        self._extractor_launch_dialog = dialog
        self._extractor_launch_attempt = 0
        QTimer.singleShot(500, self._confirm_extractor_launch)

    def _close_extractor_launch_dialog(self) -> None:
        dialog = getattr(self, "_extractor_launch_dialog", None)
        if dialog is not None:
            dialog.close()
            self._extractor_launch_dialog = None

    def _subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("OMP_NUM_THREADS", "1")
        env.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
        return env

    def _resolve_launch_python(self) -> Path:
        venv = APP_ROOT / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / (
            "python.exe" if sys.platform == "win32" else "python"
        )
        if venv.exists():
            return venv
        return Path(sys.executable)

    def _confirm_extractor_launch(self) -> None:
        proc = self._extractor_process
        if proc is None:
            self._close_extractor_launch_dialog()
            return
        attempt = getattr(self, "_extractor_launch_attempt", 0) + 1
        self._extractor_launch_attempt = attempt
        dialog = getattr(self, "_extractor_launch_dialog", None)
        if dialog is not None:
            dialog.setLabelText(
                "動画フレーム抜き出しを起動しています…\n\n"
                f"待機: {attempt // 2} 秒"
            )
        if proc.poll() is not None:
            self._close_extractor_launch_dialog()
            self._extractor_process = None
            QMessageBox.critical(
                self,
                "起動に失敗",
                f"動画フレーム抜き出しがすぐ終了しました（コード {proc.returncode}）。",
            )
            return
        if self._activate_extractor():
            self._close_extractor_launch_dialog()
            self.statusBar().showMessage("動画フレーム抜き出しを起動しました", 5000)
            return
        if attempt >= 60:
            self._close_extractor_launch_dialog()
            self.statusBar().showMessage(
                "動画フレーム抜き出しを起動しました。Dock のウィンドウを確認してください。",
                8000,
            )
            return
        QTimer.singleShot(500, self._confirm_extractor_launch)

    def _activate_extractor(self, timeout_ms: int = 1000) -> bool:
        sock = QLocalSocket()
        sock.connectToServer(EXTRACTOR_IPC_NAME)
        if not sock.waitForConnected(timeout_ms):
            return False
        sock.write(b'{"action":"activate"}\n')
        sock.waitForBytesWritten(800)
        sock.disconnectFromServer()
        return True

    def _dialog_dir(self, key: str, fallback: Path | None = None) -> str:
        saved = str(self._settings.value(f"last_dir/{key}", "") or "")
        if saved and Path(saved).is_dir():
            return saved
        if fallback is not None and Path(fallback).is_dir():
            return str(fallback)
        return str(Path.home())

    def _remember_dialog_dir(self, key: str, path: str | Path) -> None:
        target = Path(path)
        folder = target if target.is_dir() else target.parent
        if folder.is_dir():
            self._settings.setValue(f"last_dir/{key}", str(folder.resolve()))

    def open_files(self) -> None:
        if self._block_if_training():
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "画像を開く",
            self._dialog_dir("images"),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if files:
            self._remember_dialog_dir("images", files[0])
            self.import_paths(files)

    def paste_clipboard(self) -> None:
        if self._block_if_training():
            return
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

    def open_result_train_images(self) -> None:
        if self._block_if_training():
            return
        candidates = self._result_train_image_entries()
        if not candidates:
            QMessageBox.information(
                self,
                "resultの画像がありません",
                "動画フレーム抜き出しで教えた result の学習画像が見つかりませんでした。",
            )
            return
        self._select_place("result_coin")
        imported: list[Sample] = []
        missing = 0
        self.progress.setVisible(True)
        self.progress.setRange(0, len(candidates))
        self.progress.setValue(0)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            sync = self._data_sync()
            root = sync.labels_file(DATA_DIR).parent
            for index, raw in enumerate(candidates, start=1):
                self.progress.setValue(index)
                self.statusBar().showMessage(f"resultの学習画像を開いています {index}/{len(candidates)}")
                QApplication.processEvents()
                path = sync.resolve_sample_path(raw, root)
                if path is None:
                    missing += 1
                    continue
                try:
                    imported.append(self.dataset.import_file(path, save=False))
                except Exception as exc:  # noqa: BLE001
                    QApplication.restoreOverrideCursor()
                    QMessageBox.warning(self, "読み込みに失敗", f"{path.name}\n{exc}")
                    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            if imported:
                self.dataset.save()
        finally:
            QApplication.restoreOverrideCursor()
            self.progress.setVisible(False)
        if not imported:
            extra = f"\n見つからない画像が {missing} 枚ありました。" if missing else ""
            QMessageBox.information(self, "開けませんでした", f"resultの学習画像を開けませんでした。{extra}")
            return
        self._after_import(imported, predict=False)
        target = next((sample for sample in imported if "result_coin" not in sample.confirmed), imported[0])
        self.refresh_list(select_id=target.id)
        self.show_sample(target.id)
        extra = f"（見つからない {missing} 枚は除きました）" if missing else ""
        self.statusBar().showMessage(
            f"resultの学習画像 {len(imported)} 枚を開きました。リザルトのコインを囲んで保存してください{extra}",
            6000,
        )

    def _result_train_image_entries(self) -> list[str]:
        payload = self._data_sync().read_scene_payload(DATA_DIR)
        found: list[str] = []
        seen: set[str] = set()
        for item in payload.get("samples") or []:
            kind = str(item.get("kind") or "").strip().lower()
            if kind != "result":
                continue
            raw = str(item.get("path") or "").strip()
            if not raw or raw in seen:
                continue
            seen.add(raw)
            found.append(raw)
        return found

    def _select_place(self, key: str) -> None:
        item = self._place_item(key)
        if item is None:
            return
        self.region_list.setCurrentItem(item)
        if item.checkState() != Qt.CheckState.Checked:
            self.region_list.blockSignals(True)
            item.setCheckState(Qt.CheckState.Checked)
            self.region_list.blockSignals(False)
            self._apply_visible_keys()

    def import_paths(self, paths: list[str]) -> None:
        if self._block_if_training():
            return
        imported: list[Sample] = []
        for raw in paths:
            path = Path(raw)
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if not imported:
                self._remember_dialog_dir("images", path)
            try:
                imported.append(self.dataset.import_file(path))
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "読み込みに失敗", f"{path.name}\n{exc}")
        if not imported:
            return
        self._after_import(imported)

    def import_qimage(self, image) -> None:
        if self._block_if_training():
            return
        try:
            sample = self.dataset.import_qimage(image, "clipboard.png")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "貼り付けに失敗", str(exc))
            return
        self._after_import([sample])

    def _after_import(self, samples: list[Sample], predict: bool = True) -> None:
        predicted = 0
        if predict and self.predictor.is_ready():
            for sample in samples:
                if sample.status != "unlabeled":
                    continue
                try:
                    if self._predict_into_sample(sample):
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
            self.statusBar().showMessage(f"{len(samples)} 枚を取り込みました。種類を選んで囲み、その種類を保存してください", 4000)

    def on_region_changed(self, x: int, y: int, w: int, h: int) -> None:
        self._set_dirty(self._active_needs_save())
        self._refresh_region_list()

    def on_region_committed(self, x: int, y: int, w: int, h: int) -> None:
        self._set_dirty(self._active_needs_save())
        self._refresh_region_list()
        name = PLACE_LABELS.get(self._active_key, "範囲")
        self.statusBar().showMessage(f"「{name}」はまだ保存していません。「{name}」を保存すると確定します", 4000)

    def on_pieces_changed(self) -> None:
        self._set_dirty(self._active_needs_save())
        self._refresh_region_list()
        self._refresh_group_strip()
        self.update_stats()

    def _refresh_group_strip(self) -> None:
        window = getattr(self, "_group_window", None)
        if window is None or not window.isVisible():
            return
        window.set_pieces(
            self.canvas.source_pixmap(),
            self.canvas.all_pieces(),
            selected=self.canvas.selected_piece_index(),
        )

    def open_group_list(self) -> None:
        if self._group_window is None:
            self._group_window = GroupListWindow(self)
            self._group_window.pieceClicked.connect(self.canvas.select_piece)
            self._group_window.pieceRemoveRequested.connect(self._remove_listed_piece)
            self._group_window.groupChanged.connect(self.canvas.set_piece_group)
        frame = self.frameGeometry()
        width = max(1, frame.width() // 2)
        x = frame.x() + frame.width()
        screen = self.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            if x + width > avail.x() + avail.width():
                x = avail.x() + avail.width() - width
            x = max(avail.x(), x)
        self._group_window.setGeometry(x, frame.y(), width, frame.height())
        self._group_window.set_pieces(
            self.canvas.source_pixmap(),
            self.canvas.all_pieces(),
            selected=self.canvas.selected_piece_index(),
        )
        self._group_window.show()
        self._group_window.raise_()
        self._group_window.activateWindow()

    def _remove_listed_piece(self, index: int) -> None:
        self.canvas.select_piece(index)
        self.canvas.remove_selected_piece()

    def on_group_changed(self, value: int) -> None:
        self.canvas.set_piece_group(value)

    def trace_chain_candidate(self, index: int) -> None:
        if not self.canvas.start_chain_trace(index):
            self.statusBar().showMessage("つなげられるチェーンがありません", 3000)

    def on_piece_group_changed(self, value: int) -> None:
        self.spin_group.blockSignals(True)
        self.spin_group.setValue(value)
        self.spin_group.blockSignals(False)

    def _set_dirty(self, dirty: bool) -> None:
        changed = self._dirty != dirty
        self._dirty = dirty
        self.confirm_btn.setText(self._confirm_btn_label())
        if changed:
            self.update_stats()
        else:
            has_active = any(self._key_has_content(key) for key in self._selected_place_keys())
            self.confirm_btn.setEnabled(self.current_id is not None and has_active)

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        if not self._active_needs_save():
            self._set_dirty(False)
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

    def confirm_current(self) -> None:
        if self._block_if_training():
            return
        self.save_current_region()

    def save_current_region(self) -> bool:
        if not self.current_id:
            return False
        keys = self._selected_place_keys()
        ready = [key for key in keys if self._key_has_content(key)]
        scene_ready = [key for key in ready if is_scene_key(key)]
        if len(scene_ready) > 1:
            keep = self._active_key if self._active_key in scene_ready else scene_ready[0]
            ready = [key for key in ready if not is_scene_key(key) or key == keep]
        missing = [key for key in keys if key not in ready]
        if not ready:
            names = "、".join(PLACE_LABELS.get(key, key) for key in keys)
            QMessageBox.information(self, "まだありません", f"選んだ「{names}」に、まだ枠や〇がありません。")
            return False
        if any(is_piece_key(key) for key in ready) and "game" not in self.canvas.all_region_boxes():
            QMessageBox.information(self, "ゲーム範囲がありません", "ツムとボムにはゲーム範囲が必要です。先にゲーム範囲を囲んでください。")
            return False
        if not any(self._key_needs_save(key) for key in ready):
            names = "、".join(PLACE_LABELS.get(key, key) for key in ready)
            QMessageBox.information(
                self,
                "すでに保存済みです",
                f"「{names}」は保存できています。\n直したあとにもう一度押せば上書きされます。",
            )
            return True
        saved_names: list[str] = []
        for key in ready:
            saved_names.append(self._save_one_key(key))
        self._set_dirty(False)
        self.refresh_list(select_id=self.current_id)
        self._refresh_region_list()
        self._apply_sample_hint()
        self.update_stats()
        toast = "、".join(saved_names)
        extra = ""
        if missing:
            extra = "。枠のない " + "、".join(PLACE_LABELS.get(key, key) for key in missing) + " は飛ばしました"
        self.statusBar().showMessage(f"保存しました: {toast}{extra}", 4000)
        self._show_save_toast(toast)
        return True

    def _save_one_key(self, key: str) -> str:
        name = PLACE_LABELS.get(key, "範囲")
        if is_scene_key(key):
            self.dataset.confirm_key(self.current_id, key)
            return name
        if is_piece_key(key):
            pieces = [piece for piece in self.canvas.all_pieces() if piece["kind"] == key]
            expected = self.canvas.radius_for_kind(key)
            cleaned = []
            for piece in pieces:
                item = dict(piece)
                if int(item.get("r") or 0) < expected * 0.5:
                    item["r"] = expected
                cleaned.append(item)
            self.dataset.confirm_key(self.current_id, key, pieces=cleaned)
            for piece in cleaned:
                self._last_piece_radius[key] = int(piece["r"])
            return f"{name} {len(cleaned)}"
        box = self.canvas.all_region_boxes()[key]
        self.dataset.confirm_key(self.current_id, key, box=box)
        self._last_boxes[key] = dict(box)
        return name

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
        self.confirm_btn.setText(self._confirm_btn_label())

    def skip_current(self) -> None:
        if self._block_if_training() or not self.current_id:
            return
        self._set_dirty(False)
        self.dataset.skip(self.current_id)
        self._advance_after_action("使わない画像にしました")

    def _advance_after_action(self, message: str) -> None:
        next_id = self.dataset.next_pending(self.current_id)
        self.refresh_list(select_id=next_id or self.current_id)
        if next_id:
            self.show_sample(next_id)
            self.statusBar().showMessage(f"{message}。次の画像です", 4000)
        elif self.current_id:
            self.show_sample(self.current_id)
            self.statusBar().showMessage(message, 4000)

    def undo_last_piece(self) -> None:
        if self._block_if_training() or not self.current_id or not is_piece_key(self._active_key):
            return
        if not self.canvas.undo_last_piece(self._active_key):
            return
        name = PLACE_LABELS.get(self._active_key, "〇")
        self.statusBar().showMessage(f"「{name}」を1つ戻しました", 3000)
        self.update_stats()

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
        self._refresh_region_list()
        self._apply_sample_hint()
        self.update_stats()
        name = PLACE_LABELS.get(self._active_key, "範囲")
        self.statusBar().showMessage(f"「{name}」を消しました", 3000)

    def _update_unused_delete_buttons(self) -> None:
        showing = self.show_unused_chk.isChecked()
        unused = [sample for sample in self.dataset.all() if sample.status == "skipped"]
        current = self.dataset.get(self.current_id) if self.current_id else None
        self.delete_unused_one_btn.setVisible(showing)
        self.delete_unused_btn.setVisible(showing)
        self.delete_unused_one_btn.setEnabled(
            showing and current is not None and current.status == "skipped"
        )
        self.delete_unused_btn.setEnabled(showing and bool(unused))

    def delete_current(self) -> None:
        if self._block_if_training() or not self.current_id:
            return
        sample = self.dataset.get(self.current_id)
        name = sample.source_name if sample else self.current_id
        answer = QMessageBox.question(self, "削除", f"{name} をデータセットから削除しますか？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed_id = self.current_id
        next_id = self._neighbor_list_id(removed_id)
        self.dataset.remove(removed_id)
        self.current_id = None
        self.canvas.clear_image()
        self._set_dirty(False)
        self.refresh_list(select_id=next_id)
        if next_id:
            self.show_sample(next_id)
        self.statusBar().showMessage(f"{name} を削除しました", 4000)

    def register_skill_image(self) -> None:
        try:
            self._register_skill_image()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "登録できませんでした", str(exc))

    def _register_skill_image(self) -> None:
        if self._block_if_training():
            return
        sample_id = self.current_id or self._list_id_at(self.list_widget.currentRow())
        sample = self.dataset.get(sample_id) if sample_id else None
        if sample is None or not sample.image_path.is_file():
            QMessageBox.information(self, "SKILL画像として登録", "画像を選んでから使ってください。")
            return
        choices = skill_tsum_choices()
        if not choices:
            QMessageBox.information(
                self,
                "SKILL画像として登録",
                "登録できるスキルがありません。",
            )
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("SKILL画像として登録")
        dialog.setModal(True)
        dialog.setMinimumSize(360, 280)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("どのスキルですか？"))
        name_list = QListWidget()
        for tsum_id, display in choices:
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, tsum_id)
            name_list.addItem(item)
        name_list.setCurrentRow(0)
        layout.addWidget(name_list, 1)
        buttons = QDialogButtonBox()
        ok_btn = buttons.addButton("登録する", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = buttons.addButton("やめる", QDialogButtonBox.ButtonRole.RejectRole)
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        layout.addWidget(buttons)
        name_list.itemDoubleClicked.connect(lambda *_: dialog.accept())
        dialog.raise_()
        dialog.activateWindow()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        row = name_list.currentItem()
        if row is None:
            QMessageBox.information(self, "SKILL画像として登録", "スキルを選んでください。")
            return
        tsum_id = str(row.data(Qt.ItemDataRole.UserRole) or "")
        display = row.text()
        if not tsum_id:
            return
        dest = save_skill_image(sample.image_path, tsum_id, sample.id)
        self.refresh_list(select_id=sample.id)
        self._apply_sample_hint(sample)
        QMessageBox.information(
            self,
            "SKILL画像として登録",
            f"{display} のスキル画像に登録しました。\n{dest.name}",
        )
        self.statusBar().showMessage(f"{display} のスキル画像に登録しました。{dest.name}", 5000)

    def on_show_unused_toggled(self) -> None:
        select = self.current_id
        sample = self.dataset.get(select) if select else None
        if sample is not None and sample.status == "skipped" and not self.show_unused_chk.isChecked():
            select = self.dataset.next_pending(select)
            if select is None:
                visible = self._visible_samples()
                select = visible[0].id if visible else None
            if select is None:
                self.current_id = None
                self.canvas.clear_image()
                self._set_dirty(False)
        self.refresh_list(select_id=select)
        if select and select != self.current_id:
            self.show_sample(select)

    def delete_unused_images(self) -> None:
        if self._block_if_training():
            return
        unused = [sample for sample in self.dataset.all() if sample.status == "skipped"]
        if not unused:
            QMessageBox.information(self, "使わない画像", "使わない画像はありません。")
            return
        answer = QMessageBox.question(
            self,
            "使わない画像を消す",
            f"使わない {len(unused)} 枚をデータセットから削除しますか？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        current_unused = self.current_id in {sample.id for sample in unused} if self.current_id else False
        self.dataset.remove_many([sample.id for sample in unused])
        if current_unused:
            self.current_id = None
            self.canvas.clear_image()
            self._set_dirty(False)
        next_id = self.current_id or (self._visible_samples()[0].id if self._visible_samples() else None)
        self.refresh_list(select_id=next_id)
        if next_id and next_id != self.current_id:
            self.show_sample(next_id)
        self.statusBar().showMessage(f"使わない画像を {len(unused)} 枚消しました", 4000)

    def _resolved_path(self, path: Path) -> Path:
        try:
            return path.resolve()
        except OSError:
            return path.absolute()

    def _is_same_or_inside(self, path: Path, root: Path) -> bool:
        resolved = self._resolved_path(path)
        base = self._resolved_path(root)
        return resolved == base or base in resolved.parents

    def _data_sync(self):
        cached = getattr(self, "_data_sync_mod", None)
        if cached is not None:
            return cached
        spec = importlib.util.spec_from_file_location("workshop_data_sync", DATA_SYNC_PATH)
        if spec is None or spec.loader is None:
            raise FileNotFoundError(f"dataの共通処理が見つかりません。\n{DATA_SYNC_PATH}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._data_sync_mod = module
        return module

    def _server_sync(self):
        spec = importlib.util.spec_from_file_location("workshop_server_sync", SERVER_SYNC_PATH)
        if spec is None or spec.loader is None:
            raise FileNotFoundError(f"サーバー同期が見つかりません。\n{SERVER_SYNC_PATH}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._server_sync_mod = module
        return module

    def edit_server_settings(self) -> None:
        if self._server_sync().edit_settings(self):
            self.statusBar().showMessage("サーバー接続を保存しました", 4000)

    def upload_data_to_server(self) -> None:
        if self._block_if_training():
            return
        sync = self._server_sync()
        answer = QMessageBox.question(
            self,
            "サーバーに保存",
            "今のPCの内容でサーバーを上書きします。管理画面で種類を直したあとは、先に「サーバーから開く」をしてください。続けますか？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            packed = self._pack_scene_into_data()
            if not DATA_DIR.exists():
                raise FileNotFoundError(f"送るフォルダがありません。\n{DATA_DIR}")
            report = sync.run_with_progress(
                self,
                "サーバーに保存しています",
                lambda progress: sync.upload_data_dir(DATA_DIR, progress),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "保存できませんでした", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        extra = f"画面の学習画像 {packed.get('images', 0)} 枚"
        title, body = sync.format_upload_report(report, extra)
        QMessageBox.information(self, title, body)

    def download_data_from_server(self) -> None:
        if self._block_if_training():
            return
        answer = QMessageBox.question(
            self,
            "サーバーから開く",
            "サーバーの画像・種類・モデルで、今のPCの内容を置き換えます。管理画面で直した種類も、ここで取り込まれます。続けますか？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self._confirm_discard():
            return
        import shutil
        import tempfile

        sync = self._server_sync()
        tmp = Path(tempfile.mkdtemp(prefix="workshop_dl_"))
        self.current_id = None
        self.canvas.clear_image()
        self.predictor.release()
        QApplication.processEvents()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            sync.run_with_progress(
                self,
                "サーバーから開いています",
                lambda progress: sync.download_data_dir(tmp, progress),
            )
            self._data_sync().import_data_folder(DATA_DIR, tmp)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "開けませんでした", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            shutil.rmtree(tmp, ignore_errors=True)
        self._reload_after_data_import()
        self._notify_extractor("reload-scene")
        QMessageBox.information(self, "開きました", "サーバーの画像とモデルを取り込みました。")

    def _notify_extractor(self, action: str) -> None:
        sock = QLocalSocket()
        sock.connectToServer(EXTRACTOR_IPC_NAME)
        if not sock.waitForConnected(400):
            return
        sock.write(json.dumps({"action": action}, ensure_ascii=False).encode("utf-8") + b"\n")
        sock.waitForBytesWritten(800)
        sock.disconnectFromServer()

    def _pack_scene_into_data(self) -> dict[str, int]:
        return self._data_sync().ensure_scene_packed(DATA_DIR)

    def copy_data_folder(self) -> None:
        if self._block_if_training():
            return
        dest_parent = QFileDialog.getExistingDirectory(self, "貼り付ける場所を選ぶ", self._dialog_dir("copy_data"))
        if not dest_parent:
            return
        self._remember_dialog_dir("copy_data", dest_parent)
        dest_parent_path = Path(dest_parent)
        dest = dest_parent_path / DATA_DIR.name
        if self._is_same_or_inside(dest, DATA_DIR) or self._is_same_or_inside(dest_parent_path, DATA_DIR):
            QMessageBox.warning(
                self,
                "コピーできません",
                "今使っている data と同じ場所、またはその中にはコピーできません。",
            )
            return
        if dest.exists():
            answer = QMessageBox.question(
                self,
                "すでにあります",
                f"{dest}\nすでに data フォルダがあります。中身を置き換えますか？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            packed = self._pack_scene_into_data()
            if not DATA_DIR.exists():
                raise FileNotFoundError(f"コピーするフォルダがありません。\n{DATA_DIR}")
            dest = self._data_sync().copy_data_folder(DATA_DIR, dest_parent_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "コピーに失敗", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        extra = f"\n画面の学習画像 {packed.get('images', 0)} 枚"
        if packed.get("missing"):
            extra += f"（見つからない画像 {packed['missing']} 枚は除きました）"
        self.statusBar().showMessage(f"dataをコピーしました: {dest}", 5000)
        QMessageBox.information(
            self,
            "コピーしました",
            f"ツムの data と、画面の学習データをコピーしました。\n{dest}{extra}",
        )

    def _ensure_app_icon(self) -> Path | None:
        path = APP_ROOT / "app.ico"
        if path.exists():
            return path
        try:
            from PIL import Image, ImageDraw
        except Exception:
            return None
        image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((28, 8, 118, 98), fill=(255, 224, 102, 255), outline=(32, 28, 40, 255), width=8)
        draw.ellipse((138, 8, 228, 98), fill=(255, 224, 102, 255), outline=(32, 28, 40, 255), width=8)
        draw.ellipse((18, 48, 238, 248), fill=(255, 224, 102, 255), outline=(32, 28, 40, 255), width=10)
        draw.ellipse((78, 118, 108, 148), fill=(32, 28, 40, 255))
        draw.ellipse((148, 118, 178, 148), fill=(32, 28, 40, 255))
        image.save(path, format="ICO", sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
        return path

    def _create_macos_launch_shortcut(self, desktop: Path) -> Path:
        app_name = "ツムツム ゲーム範囲トレーナー.app"
        app_path = desktop / app_name
        contents = app_path / "Contents"
        macos_dir = contents / "MacOS"
        if app_path.exists():
            import shutil

            shutil.rmtree(app_path)
        macos_dir.mkdir(parents=True, exist_ok=True)
        python = self._resolve_launch_python()
        launcher = macos_dir / "launch"
        launcher.write_text(
            "#!/bin/bash\n"
            "export OMP_NUM_THREADS=1\n"
            "export KMP_DUPLICATE_LIB_OK=TRUE\n"
            f'cd "{APP_ROOT}"\n'
            f'exec "{python}" main.py\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        (contents / "Info.plist").write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIdentifier</key><string>workshop.tsumtsum-screen-trainer</string>
  <key>CFBundleName</key><string>ツムツム ゲーム範囲トレーナー</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
</dict>
</plist>
""",
            encoding="utf-8",
        )
        return app_path

    def create_launch_shortcut(self) -> None:
        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        if not desktop:
            QMessageBox.warning(self, "デスクトップがありません", "デスクトップの場所が分かりませんでした。")
            return
        if sys.platform == "darwin":
            dest = self._create_macos_launch_shortcut(Path(desktop))
            QMessageBox.information(self, "起動アイコン", f"デスクトップに作りました。\n{dest}")
            return
        lnk = Path(desktop) / "ツムツム ゲーム範囲トレーナー.lnk"
        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        target = pythonw if pythonw.exists() else python
        script = APP_ROOT / "main.py"
        icon = self._ensure_app_icon()

        def ps_quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        icon_line = f"$s.IconLocation = {ps_quote(str(icon) + ',0')}" if icon else ""
        command = (
            "$ws = New-Object -ComObject WScript.Shell\n"
            f"$s = $ws.CreateShortcut({ps_quote(str(lnk))})\n"
            f"$s.TargetPath = {ps_quote(str(target))}\n"
            f"$s.Arguments = {ps_quote(chr(34) + str(script) + chr(34))}\n"
            f"$s.WorkingDirectory = {ps_quote(str(APP_ROOT))}\n"
            "$s.WindowStyle = 1\n"
            "$s.Description = 'ツムツム ゲーム範囲トレーナー'\n"
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

    def _looks_like_data_dir(self, path: Path) -> bool:
        return self._data_sync().looks_like_data_dir(path)

    def _resolve_data_dir(self, path: Path) -> Path | None:
        return self._data_sync().resolve_data_dir(path)

    def _reload_after_data_import(self) -> None:
        if self._is_training():
            return
        self.current_id = None
        self.canvas.clear_image()
        try:
            self.predictor.release()
        except Exception:
            pass
        self.dataset.reload()
        self.predictor.reload()
        self._remember_last_boxes()
        self.refresh_list()
        self.statusBar().showMessage("dataを取り込みました", 5000)

    def import_data_folder(self) -> None:
        if self._block_if_training():
            return
        chosen = QFileDialog.getExistingDirectory(self, "取り込む data を選ぶ", self._dialog_dir("import_data"))
        if not chosen:
            return
        self._remember_dialog_dir("import_data", chosen)
        source = self._resolve_data_dir(Path(chosen))
        if source is None:
            QMessageBox.warning(
                self,
                "dataではありません",
                "index.json か、画像の入った images か、モデルの入った models か、画面の学習データがあるフォルダを選んでください。",
            )
            return
        if self._resolved_path(source) == self._resolved_path(DATA_DIR):
            QMessageBox.information(self, "同じ場所です", "今使っている data と同じ場所です。")
            return
        if self._is_same_or_inside(DATA_DIR, source):
            QMessageBox.warning(
                self,
                "取り込めません",
                "今使っている data を含むフォルダは取り込めません。",
            )
            return
        answer = QMessageBox.question(
            self,
            "dataを取り込む",
            "今のツムの画像・枠・モデルと、画面の学習データを、選んだ data で置き換えます。続けますか？\n"
            "画面の学習データが入っていない古い data のときは、今の画面学習はそのまま残します。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self._confirm_discard():
            return
        self.current_id = None
        self.canvas.clear_image()
        self.predictor.release()
        QApplication.processEvents()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._data_sync().import_data_folder(DATA_DIR, source)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "取り込みに失敗", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._reload_after_data_import()
        self._notify_extractor("reload-scene")
        QMessageBox.information(self, "取り込みました", "ツムの data と、画面の学習データを取り込みました。")

    def read_coin_number(self) -> None:
        if self._block_if_training() or not self.current_id:
            return
        sample = self.dataset.get(self.current_id)
        boxes = self.canvas.all_region_boxes()
        key = self._coin_read_key(boxes)
        box = boxes.get(key) if key else None
        if sample is None or key is None or box is None:
            QMessageBox.information(self, "コインの枠がありません", "先にコインの枠を囲んでください。")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            crop, number = ocr_coin_number(
                sample.image_path,
                box,
                predict_fn=(lambda crop, box_key=key: self.predictor.predict_coin_digits(crop, box_key))
                if self.predictor.digit_model
                else None,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "数字を取れませんでした", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        dialog = CoinNumberDialog(crop, number, self)
        dialog.exec()
        if dialog.taught and dialog.number():
            self.dataset.set_reading(self.current_id, key, dialog.number())
            self.refresh_list(select_id=self.current_id)
            self.statusBar().showMessage(f"コイン {dialog.number()} を教えました。学習すると次から使います", 5000)
        elif dialog.number():
            self.statusBar().showMessage(f"コイン {dialog.number()}", 5000)

    def _coin_read_key(self, boxes: dict[str, dict[str, int]] | None = None) -> str | None:
        boxes = boxes if boxes is not None else self.canvas.all_region_boxes()
        if is_coin_box_key(self._active_key) and self._active_key in boxes:
            return self._active_key
        for key in COIN_BOX_KEYS:
            if key in boxes:
                return key
        return None

    def predict_current(self) -> None:
        if not self.current_id or not self.predictor.is_ready():
            return
        sample = self.dataset.get(self.current_id)
        if sample is None:
            return
        try:
            added = self._predict_into_sample(sample)
            self.refresh_list(select_id=sample.id)
            self.show_sample(sample.id)
            if added:
                names = "、".join(PLACE_LABELS.get(key, key) for key in added)
                self.statusBar().showMessage(f"予測を入れました: {names}。合っていれば保存してください", 4000)
            else:
                self.statusBar().showMessage("保存済みの場所はそのままです。足りない場所はありませんでした", 4000)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "予測に失敗", str(exc))

    def _trainable_jobs(self) -> list[tuple]:
        selected = set(self._selected_place_keys())
        jobs: list[tuple] = []
        for key in REGION_KEYS:
            if key not in selected:
                continue
            samples = self.dataset.labeled_for(key)
            if len(samples) >= MIN_TRAIN_SAMPLES:
                jobs.append((key, samples, self.dataset.model_path_for(key), self._job_label(key)))
        piece_keys = [key for key in PIECE_KEYS if key in selected]
        if piece_keys:
            piece_map = {
                sample.id: sample
                for key in piece_keys
                for sample in self.dataset.labeled_for(key)
            }
            piece_samples = list(piece_map.values())
            if len(piece_samples) >= MIN_TRAIN_SAMPLES:
                if "tsum" in piece_keys:
                    type_samples = [
                        sample
                        for sample in piece_samples
                        if len(
                            {
                                int(piece.get("group") or 1)
                                for piece in sample.pieces
                                if piece.get("kind") == "tsum"
                            }
                        )
                        >= 2
                    ]
                    if len(type_samples) >= MIN_TRAIN_SAMPLES:
                        jobs.append(
                            (
                                "tsum_types",
                                type_samples,
                                self.dataset.model_path_for("tsum_types"),
                                "ツムの種類",
                            )
                        )
                jobs.append(
                    (
                        "pieces",
                        piece_samples,
                        self.dataset.model_path_for("pieces"),
                        self._piece_job_label(piece_keys),
                    )
                )
        if set(selected) & set(COIN_BOX_KEYS):
            digit_samples = self.dataset.labeled_digit_samples()
            if len(digit_samples) >= MIN_TRAIN_SAMPLES:
                jobs.append(
                    (
                        "coin_digits",
                        digit_samples,
                        self.dataset.model_path_for("coin_digits"),
                        "コインの数字",
                    )
                )
        scene_selected = [key for key in SCENE_KEYS if key in selected]
        if scene_selected:
            playable = [sample for sample in self.dataset.all() if sample.status != "skipped"]
            others = self._scene_other_count()
            if (
                all(len(self.dataset.labeled_for(key)) >= MIN_TRAIN_SAMPLES for key in scene_selected)
                and others >= MIN_TRAIN_SAMPLES
            ):
                jobs.append(
                    (
                        "scene",
                        playable,
                        self.dataset.model_path_for("scene"),
                        "GO・TIME UP",
                    )
                )
        return jobs

    def _scene_other_count(self) -> int:
        return sum(
            1
            for sample in self.dataset.all()
            if sample.status != "skipped"
            and not any(key in sample.confirmed for key in SCENE_KEYS)
        )

    def _piece_job_label(self, keys: list[str] | None = None) -> str:
        selected = keys or [key for key in PIECE_KEYS if key in self._selected_place_keys()]
        if not selected:
            selected = list(PIECE_KEYS)
        return "・".join(PLACE_LABELS[key] for key in selected)

    def _job_label(self, key: str) -> str:
        if key == "pieces":
            return self._piece_job_label()
        if key == "tsum_types":
            return "ツムの種類"
        if key == "coin_digits":
            return "コインの数字"
        if key == "scene":
            return "GO・TIME UP"
        return PLACE_LABELS.get(key, key)

    def _needs_save(self) -> bool:
        return self._active_needs_save()

    def _confirm_btn_label(self) -> str:
        if not self._active_needs_save():
            return "保存済み"
        keys = self._selected_place_keys()
        if len(keys) == 1:
            if is_scene_key(keys[0]):
                return f"この画像は{PLACE_LABELS.get(keys[0], keys[0])}"
            return f"「{PLACE_LABELS.get(keys[0], '範囲')}」を保存"
        return f"選んだ{len(keys)}件を保存"

    def _apply_visible_keys(self) -> None:
        self.canvas.set_visible_keys(self._selected_place_keys())

    def _place_item(self, key: str) -> QListWidgetItem | None:
        for row in range(self.region_list.count()):
            item = self.region_list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == key:
                return item
        return None

    def _list_status_keys(self) -> list[str]:
        keys = [key for key, _label, _color in PLACE_SPECS]
        coin_index = next((index for index, key in enumerate(keys) if is_coin_box_key(key)), -1)
        if coin_index >= 0 and "coin_digits" not in keys:
            keys.insert(coin_index + 1, "coin_digits")
        return keys

    def _sync_list_columns(self) -> None:
        keys = self._list_status_keys()
        headers = [LIST_STATUS_HEADERS.get(key, PLACE_LABELS.get(key, key)) for key in keys] + ["ファイル"]
        header = self.list_widget.horizontalHeader()
        self.list_widget.setColumnCount(len(headers))
        self.list_widget.setHorizontalHeaderLabels(headers)
        for col, key in enumerate(keys):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.list_widget.setColumnWidth(col, LIST_STATUS_WIDTHS.get(key, 88))
        header.setSectionResizeMode(len(keys), QHeaderView.ResizeMode.Stretch)
        header.setSortIndicatorShown(False)

    def _selected_place_keys(self) -> list[str]:
        keys: list[str] = []
        for row in range(self.region_list.count()):
            item = self.region_list.item(row)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            key = item.data(Qt.ItemDataRole.UserRole)
            if key:
                keys.append(key)
        if not keys and self._active_key:
            return [self._active_key]
        return keys

    def _key_has_content(self, key: str) -> bool:
        if is_scene_key(key):
            return self.canvas.has_image()
        if is_piece_key(key):
            return self.canvas.has_piece_of_kind(key)
        return key in self.canvas.all_region_boxes()

    def _active_needs_save(self) -> bool:
        return any(self._key_needs_save(key) for key in self._selected_place_keys())

    def _key_needs_save(self, key: str) -> bool:
        if not self.current_id or not self.canvas.has_image():
            return False
        sample = self.dataset.get(self.current_id)
        if is_scene_key(key):
            return sample is None or key not in sample.confirmed
        if is_piece_key(key):
            canvas = [piece for piece in self.canvas.all_pieces() if piece["kind"] == key]
            saved = [piece for piece in (sample.pieces if sample else []) if piece.get("kind") == key]
            if not canvas:
                return False
            return canvas != saved or sample is None or key not in sample.confirmed
        box = self.canvas.all_region_boxes().get(key)
        if box is None:
            return False
        saved = sample.regions.get(key) if sample else None
        return box != saved or sample is None or key not in sample.confirmed

    def _canvas_differs_from_saved(self) -> bool:
        if not self.current_id:
            return False
        sample = self.dataset.get(self.current_id)
        if sample is None:
            return True
        return self.canvas.all_region_boxes() != sample.regions or self.canvas.all_pieces() != sample.pieces

    def _is_training(self) -> bool:
        return self.train_worker is not None and self.train_worker.isRunning()

    def _training_lock_widgets(self) -> tuple:
        return (
            self.open_btn,
            self.paste_btn,
            self.confirm_btn,
            self.skip_btn,
            self.next_btn,
            self.prev_btn,
            self.clear_btn,
            self.undo_piece_btn,
            self.predict_btn,
            self.read_coin_btn,
            self.open_result_train_btn,
            self.delete_btn,
            self.skill_register_btn,
            self.delete_unused_one_btn,
            self.delete_unused_btn,
            self.copy_data_btn,
            self.import_data_btn,
            self.shortcut_btn,
            self.video_app_btn,
            self.reuse_btn,
            self.copy_box_btn,
            self.region_list,
            self.list_widget,
            self.canvas,
            self.spin_group,
        )

    def _keep_display_awake(self, on: bool) -> None:
        if sys.platform != "win32":
            return
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint]
        kernel32.SetThreadExecutionState.restype = ctypes.c_uint
        continuous = 0x80000000
        system = 0x00000001
        display = 0x00000002
        if on:
            kernel32.SetThreadExecutionState(ctypes.c_uint(continuous | system | display))
            if self._awake_timer is None:
                self._awake_timer = QTimer(self)
                self._awake_timer.timeout.connect(self._ping_display_awake)
            self._awake_timer.start(30000)
            return
        if self._awake_timer is not None:
            self._awake_timer.stop()
        kernel32.SetThreadExecutionState(ctypes.c_uint(continuous))

    def _ping_display_awake(self) -> None:
        if sys.platform != "win32":
            return
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint]
        kernel32.SetThreadExecutionState.restype = ctypes.c_uint
        kernel32.SetThreadExecutionState(ctypes.c_uint(0x80000000 | 0x00000001 | 0x00000002))

    def _lock_for_training(self) -> None:
        for widget in self._training_lock_widgets():
            widget.setEnabled(False)
        self.train_btn.setEnabled(True)
        self.train_btn.setText("中止")
        self._sync_train_shutdown_btn()
        self.hint_label.setText("学習中です。中止できます。")

    def _unlock_after_training(self) -> None:
        self._keep_display_awake(False)
        for widget in self._training_lock_widgets():
            widget.setEnabled(True)
        self.train_btn.setText("学習する")
        self._sync_train_shutdown_btn()
        self.hint_label.setText("色つきの四角が付いています。保存したい種類にチェックを付けて保存してください。")

    def _sync_train_shutdown_btn(self) -> None:
        if self._is_training():
            self.train_shutdown_btn.setEnabled(True)
            if self._shutdown_after_train:
                self.train_shutdown_btn.setText("やっぱりシャットダウンしない")
            else:
                self.train_shutdown_btn.setText("やっぱりシャットダウンする")
            if hasattr(self, "_train_fx"):
                self._train_fx.set_shutdown_after(self._shutdown_after_train)
            return
        self.train_shutdown_btn.setText("学習してシャットダウン")
        self.train_shutdown_btn.setEnabled(bool(self._trainable_jobs()) and self.train_worker is None)

    def _block_if_training(self) -> bool:
        if not self._is_training():
            return False
        self.statusBar().showMessage("学習中です。終わるまで操作できません", 3000)
        return True

    def _place_train_fx(self) -> None:
        host = self._train_fx.parentWidget() or self
        self._train_fx.setGeometry(0, 0, host.width(), host.height())
        self._train_fx.raise_()

    def _sync_canvas_3_2(self) -> None:
        if getattr(self, "_syncing_canvas", False):
            return
        col = getattr(self, "_canvas_host", None)
        split = getattr(self, "_body_split", None)
        if col is None or split is None or not hasattr(self, "canvas"):
            return
        height = col.height()
        if height < 80:
            return
        width = (height * 2) // 3
        if col.minimumWidth() == width and col.maximumWidth() == width:
            return
        self._syncing_canvas = True
        col.setMinimumWidth(width)
        col.setMaximumWidth(width)
        sizes = split.sizes()
        if len(sizes) >= 3 and sizes[1] != width:
            leftover = sizes[1] - width
            sizes[1] = width
            sizes[2] = max(480, sizes[2] + leftover)
            split.setSizes(sizes)
        self._syncing_canvas = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_canvas_3_2()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "canvas"):
            self._sync_canvas_3_2()
        if hasattr(self, "_train_fx"):
            self._place_train_fx()

    def _train_eta_line(self, seconds: float) -> str:
        seconds = max(1.0, seconds)
        elapsed = max(0, int(seconds))
        hours, rest = divmod(elapsed, 3600)
        minutes, secs = divmod(rest, 60)
        if hours:
            duration = f"{hours}時間{minutes:02d}分{secs:02d}秒"
        else:
            duration = f"{minutes:02d}分{secs:02d}秒"
        clock = (datetime.now() + timedelta(seconds=seconds)).strftime("%H:%M")
        return f"予想完了時間  {clock}頃（約{duration}）"

    def _cuda_available(self) -> bool:
        if self._cuda_ready is None:
            try:
                import torch

                self._cuda_ready = bool(torch.cuda.is_available())
            except Exception:
                self._cuda_ready = False
        return self._cuda_ready

    def _train_batch_count(self, samples: int, batch_size: int) -> int:
        count = max(int(samples), 1)
        size = max(int(batch_size), 1)
        return max(1, math.ceil(count / min(size, count)))

    def _train_batch_rate(self, default: float) -> float:
        try:
            rate = float(self._settings.value("train_sec_per_batch", default) or default)
        except (TypeError, ValueError):
            rate = default
        return min(max(rate, 0.05), 20.0)

    def _estimate_jobs_seconds(self, jobs: list) -> float:
        cuda = self._cuda_available()
        default = 0.3 if cuda else 1.8
        rate = self._train_batch_rate(default)
        total = 0.0
        for job in jobs:
            key = str(job[0])
            samples = job[1] if len(job) > 1 else []
            n = max(len(samples), 1)
            batch = 8 if key == "scene" else 4
            overhead = 15.0 if key == "scene" else 8.0
            total += overhead + TRAIN_EPOCHS * self._train_batch_count(n, batch) * rate
        return max(total, 5.0)

    def _remember_train_duration(self, jobs: list, started_at: float | None) -> None:
        if started_at is None:
            return
        elapsed = time.perf_counter() - started_at
        if elapsed < 3:
            return
        work = 0
        for job in jobs:
            key = str(job[0])
            samples = job[1] if len(job) > 1 else []
            n = max(len(samples), 1)
            batch = 8 if key == "scene" else 4
            work += TRAIN_EPOCHS * self._train_batch_count(n, batch)
        if work <= 0:
            return
        overhead = 8.0 * max(len(jobs), 1)
        observed = (elapsed - overhead) / work
        if not 0.05 <= observed <= 20.0:
            return
        default = 0.3 if self._cuda_available() else 1.8
        rate = 0.55 * self._train_batch_rate(default) + 0.45 * observed
        self._settings.setValue("train_sec_per_batch", rate)

    def start_training(self, *, shutdown_after: bool = False) -> None:
        if self._is_training():
            return
        selected = self._selected_place_keys()
        jobs = self._trainable_jobs()
        counts = self.dataset.labeled_counts()
        if not jobs:
            lines = [
                f"チェックした種類の学習には、正解が {MIN_TRAIN_SAMPLES} 枚以上必要です。",
                "",
            ]
            lines.extend(f"{PLACE_LABELS.get(key, key)}: {counts[key]} 枚" for key in selected)
            if any(key in SCENE_KEYS for key in selected):
                lines.append(f"GO/TIME UP以外: {self._scene_other_count()} 枚")
            QMessageBox.information(self, "まだ足りません", "\n".join(lines))
            return
        ready_lines = [f"{job[3]}: {len(job[1])} 枚" for job in jobs]
        trained_keys = {job[0] for job in jobs}
        skipped = []
        for key in selected:
            if key in PIECE_KEYS:
                if "pieces" in trained_keys:
                    continue
                skipped.append(f"{PLACE_LABELS[key]}: {counts[key]} 枚")
            elif key in SCENE_KEYS:
                if "scene" in trained_keys:
                    continue
                skipped.append(f"{PLACE_LABELS[key]}: {counts[key]} 枚")
            elif key not in trained_keys:
                skipped.append(f"{PLACE_LABELS.get(key, key)}: {counts[key]} 枚")
        if set(selected) & set(COIN_BOX_KEYS) and "coin_digits" not in trained_keys:
            skipped.append(f"コインの数字: {counts.get('coin_digits', 0)} 枚")
        if any(key in SCENE_KEYS for key in selected) and "scene" not in trained_keys:
            others = self._scene_other_count()
            if others < MIN_TRAIN_SAMPLES:
                skipped.append(f"GO/TIME UP以外: {others} 枚")
        message = "チェックした種類だけ学習します。\n" + "\n".join(ready_lines)
        piece_selected = [key for key in PIECE_KEYS if key in selected]
        if len(piece_selected) == 1 and "pieces" in trained_keys:
            other = "ボム" if piece_selected[0] == "tsum" else "ツム"
            message += f"\n（ツムとボムは同じモデルです。{PLACE_LABELS[piece_selected[0]]}だけ学ぶと、{other}の予測も更新されます。）"
        if skipped:
            message += "\n\n枚数が足りないので、今回は学びません。\n" + "\n".join(skipped)
        message += "\n\n" + self._train_eta_line(self._estimate_jobs_seconds(jobs))
        if shutdown_after:
            message += "\n終わったら PC をシャットダウンします。"
        answer = QMessageBox.question(self, "学習を開始", message)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._shutdown_after_train = shutdown_after
        self.progress.setVisible(True)
        self.progress.setRange(0, 40 * len(jobs))
        self.progress.setValue(0)
        self.train_worker = TrainWorker(jobs)
        self.train_worker.progress.connect(self.on_train_progress)
        self.train_worker.finished_ok.connect(self.on_train_finished)
        self.train_worker.failed.connect(self.on_train_failed)
        self._lock_for_training()
        self._keep_display_awake(True)
        self._place_train_fx()
        self._train_fx.start()
        self._train_fx.set_shutdown_after(self._shutdown_after_train)
        QApplication.processEvents()
        self._train_started_at = time.perf_counter()
        self.statusBar().showMessage("学習中です。中止できます")
        self.train_worker.start()

    def on_train_button(self) -> None:
        if self._is_training():
            self.cancel_training()
            return
        self.start_training()

    def on_train_shutdown_button(self) -> None:
        if self._is_training():
            self._shutdown_after_train = not self._shutdown_after_train
            self._sync_train_shutdown_btn()
            if self._shutdown_after_train:
                self.statusBar().showMessage("終わったらシャットダウンします", 4000)
            else:
                self.statusBar().showMessage("終わってもシャットダウンしません", 4000)
            return
        self.start_training(shutdown_after=True)

    def cancel_training(self) -> None:
        if self.train_worker is None or not self.train_worker.isRunning():
            return
        self.train_btn.setEnabled(False)
        self.train_btn.setText("中止しています…")
        self._train_fx.set_cancelling()
        self.train_worker.requestInterruption()
        self.statusBar().showMessage("学習を中止しています")

    def on_train_progress(self, epoch: int, total: int, message: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(epoch)
        self._train_fx.set_progress(epoch, total, message)
        self.statusBar().showMessage(message)
        QApplication.processEvents()

    def on_train_finished(self, metrics: dict) -> None:
        worker = self.train_worker
        self.progress.setVisible(False)
        self._train_fx.stop()
        if worker is not None:
            worker.wait(8000)
        self.train_worker = None
        self._unlock_after_training()
        try:
            self.predictor.reload()
        except Exception:
            pass
        self.update_stats()
        self.refresh_list(select_id=self.current_id)
        if self.current_id:
            self.show_sample(self.current_id)
        if metrics.get("cancelled"):
            done = metrics.get("results") or []
            extra = ""
            if done:
                names = "、".join(item.get("label", "") for item in done)
                extra = f"\n終わる前に保存できたもの: {names}"
            self._train_started_at = None
            self._shutdown_after_train = False
            QMessageBox.information(self, "学習を中止", "学習を中止しました。" + extra)
            self.statusBar().showMessage("学習を中止しました", 4000)
            return
        results = metrics.get("results") or []
        jobs = getattr(worker, "jobs", None) or []
        self._remember_train_duration(jobs, self._train_started_at)
        self._train_started_at = None
        lines = []
        for item in results:
            if item.get("key") in {"pieces", "tsum_types"}:
                lines.append(f"{item['label']}  loss {item.get('loss', 0):.4f}（{item['samples']} 枚）")
            elif item.get("key") in {"coin_digits", "scene"}:
                lines.append(f"{item['label']}  acc {item.get('iou', 0):.3f}（{item['samples']} 枚）")
        else:
            lines.append(f"{item['label']}  IoU {item['iou']:.3f}（{item['samples']} 枚）")
        if self._shutdown_after_train:
            self._shutdown_after_train = False
            self.statusBar().showMessage("学習が完了しました。シャットダウンします")
            self._shutdown_pc()
            return
        QMessageBox.information(
            self,
            "学習完了",
            "\n".join(lines) + "\n\n今の画像に予測を入れました。他の画像は開いたときに予測します。",
        )
        self.statusBar().showMessage("学習が完了しました", 4000)

    def on_train_failed(self, message: str) -> None:
        worker = self.train_worker
        self.progress.setVisible(False)
        self._train_fx.stop()
        if worker is not None:
            worker.wait(8000)
        self.train_worker = None
        self._train_started_at = None
        self._shutdown_after_train = False
        self._unlock_after_training()
        self.update_stats()
        self.hint_label.setText("学習に失敗しました。他の操作が使えます。")
        QMessageBox.critical(self, "学習に失敗", message)

    def _shutdown_pc(self) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(["shutdown", "/s", "/t", "0"], creationflags=flags)

    def _apply_predictions_to_unlabeled(self) -> int:
        if not self.predictor.is_ready():
            return 0
        applied = 0
        for sample in self.dataset.all():
            if sample.status == "skipped":
                continue
            try:
                added = self._predict_into_sample(sample)
            except Exception:
                continue
            applied += len(added)
        return applied

    def _relabel_tsum_groups(self, sample: Sample) -> bool:
        if self.predictor.type_model is None:
            return False
        if not any(piece.get("kind") == "tsum" for piece in sample.pieces):
            return False
        from PIL import Image

        pieces = [dict(piece) for piece in sample.pieces]
        before = [
            (int(piece["x"]), int(piece["y"]), int(piece.get("group") or 1))
            for piece in pieces
            if piece.get("kind") == "tsum"
        ]
        with Image.open(sample.image_path) as image:
            self.predictor._assign_groups(image.convert("RGB"), pieces)
        after = [
            (int(piece["x"]), int(piece["y"]), int(piece.get("group") or 1))
            for piece in pieces
            if piece.get("kind") == "tsum"
        ]
        if before == after:
            return False
        self.dataset.set_pieces(sample.id, pieces)
        return True

    def _predict_into_sample(self, sample: Sample, *, overwrite: bool = True) -> list[str]:
        added: list[str] = []
        boxes = self.predictor.predict_all(sample.image_path)
        if boxes:
            added.extend(self.dataset.apply_predictions(sample.id, boxes))
        sample = self.dataset.get(sample.id) or sample
        game = sample.regions.get("game") or sample.game_region
        existing_tsums = [piece for piece in sample.pieces if piece.get("kind") == "tsum"]
        tsum_locked = (not overwrite) and "tsum" in sample.confirmed
        if existing_tsums and not tsum_locked:
            if self._relabel_tsum_groups(sample):
                added.append("tsum")
            sample = self.dataset.get(sample.id) or sample
        pieces = self.predictor.predict_pieces(sample.image_path, game)
        if existing_tsums:
            pieces = [piece for piece in pieces if piece.get("kind") != "tsum"]
        if pieces:
            if not overwrite:
                existing = {str(piece.get("kind")) for piece in sample.pieces}
                confirmed = set(sample.confirmed)
                pieces = [
                    piece
                    for piece in pieces
                    if piece.get("kind") not in existing and piece.get("kind") not in confirmed
                ]
            if pieces:
                added.extend(self.dataset.apply_piece_predictions(sample.id, pieces))
        return added

    def eventFilter(self, watched, event) -> bool:
        if watched is getattr(self, "_canvas_host", None) and event.type() == QEvent.Type.Resize:
            self._sync_canvas_3_2()
        if watched is self.canvas and event.type() == QEvent.Type.Resize:
            self._place_train_fx()
        if self._is_training() and watched is self.canvas and event.type() == QEvent.Type.KeyPress:
            return True
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
        count = self.list_widget.rowCount()
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
                return self._active_key not in sample.confirmed
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
        for row in range(self.list_widget.rowCount()):
            if self._list_id_at(row) == sample_id:
                self.list_widget.setCurrentCell(row, 0)
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
            self.train_worker.requestInterruption()
            self.train_worker.wait(15000)
            self._train_fx.stop()
        self._keep_display_awake(False)
        event.accept()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._is_training():
            event.ignore()
            return
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
