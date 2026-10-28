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

from PySide6.QtCore import QEvent, QRect, QRectF, QSettings, QSize, QStandardPaths, Qt, QThread, QTimer, Signal
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
    QAbstractItemDelegate,
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
    QLayout,
    QLineEdit,
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
from app.elsa_run import elsa_three_chains
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
    SKILLS_IMAGES_DIR,
    USE_TSUM_REGISTRY,
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
    is_tsum_kind,
    model_filename,
    tsum_group_color,
)
from app.skill_export import registered_skills_by_sample, save_skill_image, skill_tsum_choices
from app.train_effect import TrainEffect
from app.tsum_chain import CANDIDATE_COUNT
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
    "big": 40,
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
    "big": "デカ\nツム",
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
QPushButton#mode:checked {
    background: #2f7fd1;
    font-weight: 600;
}
QPushButton#mode:checked:hover { background: #4590de; }
QLineEdit {
    background: #2a303b;
    color: #e8eaed;
    border: none;
    border-radius: 8px;
    padding: 8px 10px;
}
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

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        window = parent.window() if parent is not None else None
        if editor is not None and window is not None:
            editor.installEventFilter(window)
        return editor


class _GroupStripBody(QWidget):
    CELL = 80
    GAP = 6
    LABEL = 36
    COLS = 8

    pieceClicked = Signal(int)
    pieceRemoveRequested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, QColor, list[tuple[QPixmap, int]]]] = []
        self._selected: int | None = None
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_pieces(
        self,
        pixmap: QPixmap | None,
        pieces: list[dict[str, int]],
        selected: int | None = None,
    ) -> None:
        self._rows = []
        self._selected = selected
        if pixmap is None or pixmap.isNull() or not pieces:
            self.setFixedSize(self.LABEL + self.CELL, self.CELL)
            self.update()
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
        width = self.LABEL + self.COLS * (self.CELL + self.GAP)
        height = max(1, self._needed_height())
        if self.width() != width or self.height() != height:
            self.setFixedSize(width, height)
        self.update()

    def _crop(self, pixmap: QPixmap, piece: dict[str, int]) -> QPixmap:
        x, y, radius = int(piece["x"]), int(piece["y"]), max(8, int(piece.get("r") or 16))
        span = max(12, int(round(radius * 1.05)))
        tile = pixmap.copy(QRect(x - span, y - span, span * 2, span * 2))
        return tile.scaled(
            self.CELL,
            self.CELL,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

    def hasHeightForWidth(self) -> bool:
        return False

    def sizeHint(self) -> QSize:
        return QSize(self.LABEL + self.COLS * (self.CELL + self.GAP), self._needed_height())

    def minimumSizeHint(self) -> QSize:
        return QSize(self.LABEL + self.CELL, self.CELL)

    def _per_row(self, _width: int = 0) -> int:
        return self.COLS

    def _needed_height(self, _width: int = 0) -> int:
        if not self._rows:
            return 0
        per = self.COLS
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
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._body = _GroupStripBody()
        self._body.pieceClicked.connect(self.pieceClicked.emit)
        self._body.pieceRemoveRequested.connect(self.pieceRemoveRequested.emit)
        self.setWidget(self._body)

    def sizeHint(self) -> QSize:
        return QSize(480, 640)

    def minimumSizeHint(self) -> QSize:
        return QSize(160, 160)

    def hasHeightForWidth(self) -> bool:
        return False

    def set_pieces(
        self,
        pixmap: QPixmap | None,
        pieces: list[dict[str, int]],
        selected: int | None = None,
    ) -> None:
        self._body.set_pieces(pixmap, pieces, selected=selected)

    def selected_index(self) -> int | None:
        return self._body._selected


class _ClickLabel(QLabel):
    def __init__(self, text: str, callback) -> None:
        super().__init__(text)
        self.setWordWrap(True)
        self._callback = callback

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._callback()
            event.accept()
            return
        super().mousePressEvent(event)


class _NamedFace(QLabel):
    def __init__(self, pixmap: QPixmap, callback) -> None:
        super().__init__()
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self._callback = callback

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._callback()
            event.accept()
            return
        super().mousePressEvent(event)


class GroupListWindow(QDialog):
    pieceClicked = Signal(int)
    pieceRemoveRequested = Signal(int)
    tsumsClearRequested = Signal()
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
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("ツム種類"))
        self.group_label = QLabel("No.  1")
        bar.addWidget(self.group_label)
        self.group_down_btn = QPushButton("－ (-)")
        self.group_up_btn = QPushButton("＋ (+)")
        self.group_down_btn.setEnabled(False)
        self.group_up_btn.setEnabled(False)
        bar.addWidget(self.group_down_btn)
        bar.addWidget(self.group_up_btn)
        self.delete_btn = QPushButton("消す")
        self.delete_btn.setEnabled(False)
        bar.addWidget(self.delete_btn)
        self.delete_tsum_btn = QPushButton("ツムを消す")
        self.delete_tsum_btn.setEnabled(False)
        bar.addWidget(self.delete_tsum_btn)
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
        QShortcut(QKeySequence(Qt.Key.Key_Minus), self, self._nudge_group_down)
        QShortcut(QKeySequence(Qt.Key.Key_Plus), self, self._nudge_group_up)
        self.delete_btn.clicked.connect(self._on_delete)
        self.delete_tsum_btn.clicked.connect(self._on_delete_tsum)
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
        is_tsum = piece is not None and is_tsum_kind(str(piece.get("kind") or ""))
        self.delete_tsum_btn.setEnabled(any(item.get("kind") == "tsum" for item in self._pieces))
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
        if not is_tsum_kind(str(piece.get("kind") or "")):
            return 1
        return int(piece.get("group") or 1)

    def _nudge_group_down(self) -> None:
        if not self.group_down_btn.isEnabled():
            return
        group = self._current_group()
        if group > 1:
            self.groupChanged.emit(group - 1)

    def _nudge_group_up(self) -> None:
        if not self.group_up_btn.isEnabled():
            return
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

    def _on_delete_tsum(self) -> None:
        if not self.delete_tsum_btn.isEnabled():
            return
        self.tsumsClearRequested.emit()

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


class CoinReadWorker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, work) -> None:
        super().__init__()
        self._work = work

    def run(self) -> None:
        try:
            self.finished_ok.emit(self._work())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class PredictWorker(QThread):
    finished_ok = Signal(str, list)
    failed = Signal(str)

    def __init__(self, work) -> None:
        super().__init__()
        self._work = work

    def run(self) -> None:
        try:
            sample_id, added = self._work()
            self.finished_ok.emit(sample_id, added)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ツムツム ゲーム範囲トレーナー")
        icon = self._ensure_app_icon()
        if icon is not None:
            self.setWindowIcon(QIcon(str(icon)))
        self.setMinimumSize(980, 640)
        screen = QApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.availableGeometry())
        else:
            self.resize(1280, 840)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLESHEET)

        self.dataset = Dataset(DATA_DIR, load=False)
        self.predictor = Predictor(self.dataset.models_dir, load=False)
        self._data_loaded = False
        self.current_id: str | None = None
        self._active_key = "game"
        self.train_worker: TrainWorker | None = None
        self._predict_worker: PredictWorker | None = None
        self._coin_worker: CoinReadWorker | None = None
        self._train_started_at: float | None = None
        self._cuda_ready: bool | None = None
        self._dirty = False
        self._shutdown_after_train = False
        self._awake_timer: QTimer | None = None
        self._switching = False
        self._refreshing_list = False
        self._refresh_list_again: str | bool | None = False
        self._list_filling = False
        self._list_fill_restart = False
        self._extractor_process = None
        self._ipc_buffers: dict[int, bytes] = {}
        self._last_boxes: dict[str, dict[str, int]] = {}
        self._last_piece_radius: dict[str, int] = {}
        self._list_sort_key: str | None = None
        self._list_sort_asc = True
        self._file_tsum: tuple[str, str] | None = None
        self._skill_registered: dict[str, str] = {}
        self._settings = QSettings("workshop", "TsumTsumScreenTrainer")
        self._group_window: GroupListWindow | None = None
        self._syncing_canvas = False
        self._canvas_echo = False
        self._canvas_sync_h: int | None = None
        self._remember_last_boxes()

        self._build_ui()
        self._bind_shortcuts()
        self._start_ipc()
        self.update_stats()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        top = QFrame()
        top.setObjectName("topbar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(16, 8, 16, 8)
        title = QLabel("ツムツム ゲーム範囲トレーナー")
        title.setObjectName("title")
        title.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.hint_label = QLabel("画像をドロップ / Ctrl+V / 「画像を開く」。左で種類にチェックを付けて保存します。")
        self.hint_label.setObjectName("hint")
        self.hint_label.setWordWrap(False)
        self.hint_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top_layout.addWidget(title)
        top_layout.addWidget(self.hint_label, 1)

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
        self.name_mode_btn = QPushButton("ツム名を登録")
        self.name_mode_btn.setCheckable(True)
        self.name_mode_btn.setObjectName("mode")
        left_layout.addWidget(self.name_mode_btn)
        self.name_panel = QWidget()
        name_layout = QVBoxLayout(self.name_panel)
        name_layout.setContentsMargins(0, 0, 0, 0)
        self.name_faces = QWidget()
        self.name_faces_layout = QGridLayout(self.name_faces)
        self.name_faces_layout.setContentsMargins(0, 0, 0, 0)
        self.name_faces_layout.setSpacing(4)
        self.name_ja = QLineEdit()
        self.name_ja.setPlaceholderText("日本語")
        self.name_en = QLineEdit()
        self.name_en.setPlaceholderText("英語")
        self.name_save_btn = QPushButton("登録")
        self.name_saved_list = QListWidget()
        self.name_saved_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.name_saved_list.setWordWrap(True)
        self.name_saved_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.name_saved_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.name_saved_list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.name_state = QLabel("未登録")
        self.name_state.setWordWrap(True)
        name_layout.addWidget(self.name_faces)
        name_layout.addWidget(self.name_state)
        name_layout.addWidget(self.name_ja)
        name_layout.addWidget(self.name_en)
        name_layout.addWidget(self.name_save_btn)
        self.name_panel.hide()
        self._name_window = QDialog(self)
        self._name_window.setWindowTitle("ツム名")
        self._name_window.setModal(False)
        self._name_window.setStyleSheet(STYLESHEET)
        self._name_window.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        name_window_layout = QVBoxLayout(self._name_window)
        name_window_layout.setContentsMargins(8, 8, 8, 8)
        name_window_layout.addWidget(self.name_saved_list)
        left_layout.addWidget(self.name_panel)
        self.tsum_select_btn = QPushButton("ツム選択")
        left_layout.addWidget(self.tsum_select_btn)
        self.tsum_pick_row = QWidget()
        pick_layout = QHBoxLayout(self.tsum_pick_row)
        pick_layout.setContentsMargins(0, 0, 0, 0)
        self.tsum_back_btn = QPushButton("戻す")
        pick_layout.addWidget(self.tsum_back_btn)
        self.tsum_pick_row.hide()
        left_layout.addWidget(self.tsum_pick_row)
        self.tsum_name_list = QListWidget()
        self.tsum_name_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.tsum_name_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tsum_name_list.hide()
        left_layout.addWidget(self.tsum_name_list)
        self.region_list = QListWidget()
        self.region_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.region_list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
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
        self.server_save_btn = QPushButton("サーバーに保存")
        self.shortcut_btn = QPushButton("起動アイコン作成")
        left_grid = QGridLayout()
        left_grid.setContentsMargins(0, 0, 0, 0)
        left_buttons = (
            self.server_save_btn,
            self.shortcut_btn,
        )
        for i, button in enumerate(left_buttons):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            left_grid.addWidget(button, i // 2, i % 2)
        for col in range(2):
            left_grid.setColumnStretch(col, 1)
        left_layout.addLayout(left_grid)
        self.elsa_list_btn = QPushButton("エルサ")
        left_layout.addWidget(self.elsa_list_btn)
        left_layout.addStretch(1)
        left.setMinimumWidth(317)
        left.setMaximumWidth(461)

        self.canvas = ImageCanvas()
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._canvas_host = QWidget()
        self._canvas_host.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        canvas_host_layout = QVBoxLayout(self._canvas_host)
        canvas_host_layout.setContentsMargins(0, 0, 0, 0)
        canvas_host_layout.setSpacing(0)
        canvas_host_layout.addWidget(self.canvas)
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
        elsa_action_row = QHBoxLayout()
        self.elsa_run_btn = QPushButton("RUN")
        self.elsa_delete_btn = QPushButton("削除")
        self.elsa_run_btn.hide()
        self.elsa_delete_btn.hide()
        elsa_action_row.addWidget(self.elsa_run_btn)
        elsa_action_row.addWidget(self.elsa_delete_btn)
        elsa_action_row.addStretch(1)
        right_layout.addLayout(elsa_action_row)
        unused_row = QHBoxLayout()
        self.show_unused_chk = QCheckBox("使わない画像も見る")
        self.delete_unused_one_btn = QPushButton("この画像を消す")
        self.delete_unused_btn = QPushButton("使わない画像を全部消す")
        unused_row.addWidget(self.show_unused_chk, 1)
        unused_row.addWidget(self.delete_unused_one_btn)
        unused_row.addWidget(self.delete_unused_btn)
        right_layout.addLayout(unused_row)
        self.delete_unsaved_btn = QPushButton("保存していない画像を全部消す")
        right_layout.addWidget(self.delete_unsaved_btn)
        self.list_widget = QTableWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.list_widget.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
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
        splitter.setChildrenCollapsible(False)
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
        for index in range(CANDIDATE_COUNT):
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
        self.delete_unsaved_btn.clicked.connect(self.delete_unsaved_images)
        self.show_unused_chk.toggled.connect(self.on_show_unused_toggled)
        self.server_save_btn.clicked.connect(self.upload_data_to_server)
        self.elsa_list_btn.clicked.connect(self.toggle_elsa_list)
        self.elsa_run_btn.clicked.connect(self.run_elsa)
        self.elsa_delete_btn.clicked.connect(self.delete_elsa_image)
        self.shortcut_btn.clicked.connect(self.create_launch_shortcut)
        self.video_app_btn.clicked.connect(self.launch_video_extractor)
        self.list_widget.currentCellChanged.connect(self.on_list_cell_changed)
        self.list_widget.itemChanged.connect(self.on_list_item_changed)
        self.list_widget.itemDoubleClicked.connect(self._on_file_name_double_clicked)
        self.name_mode_btn.toggled.connect(self._toggle_name_mode)
        self.name_save_btn.clicked.connect(self._register_circle_name)
        self.name_ja.textChanged.connect(lambda text: self._show_existing_name("ja", text))
        self.name_en.textChanged.connect(lambda text: self._show_existing_name("en", text))
        self.name_saved_list.itemClicked.connect(self._open_saved_circle_name)
        self.tsum_select_btn.clicked.connect(self.show_tsum_list)
        self.tsum_back_btn.clicked.connect(self._restore_file_list)
        self.tsum_name_list.itemClicked.connect(self.on_tsum_name_clicked)
        self.region_list.currentItemChanged.connect(self.on_region_type_changed)
        self.region_list.itemChanged.connect(self.on_place_item_changed)
        self.canvas.regionCommitted.connect(self.on_region_committed)
        self.canvas.regionChanged.connect(self.on_region_changed)
        self.canvas.piecesChanged.connect(self.on_pieces_changed)
        self.canvas.pieceGroupChanged.connect(self.on_piece_group_changed)
        self.canvas.filesDropped.connect(self.import_paths)
        self.canvas.imageDropped.connect(self.import_qimage)
        self.canvas.installEventFilter(self)
        self.list_widget.installEventFilter(self)
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
        if not self.show_unused_chk.isChecked():
            samples = [sample for sample in samples if sample.status != "skipped"]
        chosen = getattr(self, "_file_tsum", None)
        if chosen:
            folder, shown = chosen
            samples = [sample for sample in samples if self._matches_used_tsum(sample, folder, shown)]
        return samples

    def _coin_digits_of(self, sample: Sample) -> str:
        for box_key in COIN_BOX_KEYS:
            digits = "".join(char for char in (sample.readings or {}).get(box_key, "") if char.isdigit())
            if digits:
                return digits
        return ""

    def _coin_write_key(self, sample: Sample) -> str:
        for box_key in COIN_BOX_KEYS:
            digits = "".join(char for char in (sample.readings or {}).get(box_key, "") if char.isdigit())
            if digits:
                return box_key
        for box_key in COIN_BOX_KEYS:
            if (sample.regions or {}).get(box_key):
                return box_key
        return "coin"

    def on_list_item_changed(self, item: QTableWidgetItem) -> None:
        if item is None or self._block_if_training():
            return
        keys = self._list_status_keys()
        col = item.column()
        if col < 0 or col >= len(keys) or keys[col] != "coin_digits":
            return
        sample = self.dataset.get(item.data(Qt.ItemDataRole.UserRole) or self._list_id_at(item.row()))
        if sample is None:
            return
        digits = "".join(char for char in item.text() if char.isdigit())
        self.list_widget.blockSignals(True)
        try:
            if not digits:
                self._style_list_row(item.row(), sample)
                return
            key = self._coin_write_key(sample)
            self.dataset.set_reading(sample.id, key, digits)
            item.setText(format_coin_number(digits))
            item.setForeground(QColor("#3DDC97"))
            self.statusBar().showMessage(f"コイン {format_coin_number(digits)} を直しました", 4000)
        except Exception as exc:  # noqa: BLE001
            self._style_list_row(item.row(), sample)
            QMessageBox.warning(self, "数字を保存できませんでした", str(exc))
        finally:
            self.list_widget.blockSignals(False)

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
        if getattr(self, "_elsa_list", False):
            return
        self._list_fill_select = select_id
        if self._list_filling:
            self._list_fill_restart = True
            return
        self._begin_list_fill(select_id)

    def _begin_list_fill(self, select_id: str | None = None) -> None:
        self._list_filling = True
        self._list_fill_restart = False
        self._skill_registered = registered_skills_by_sample()
        self._sync_list_columns()
        samples = self._ordered_visible_samples()
        self._list_fill_samples = samples
        self._list_fill_selected = select_id or self.current_id
        self._list_fill_scroll = self.list_widget.verticalScrollBar().value()
        self._list_fill_prev = self._list_id_at(self.list_widget.currentRow())
        existing = [self._list_id_at(row) for row in range(self.list_widget.rowCount())]
        new_ids = [sample.id for sample in samples]
        self.list_widget.blockSignals(True)
        if existing != new_ids:
            self.list_widget.setRowCount(len(samples))
        self.list_widget.blockSignals(False)
        self._list_fill_row = 0
        self._fill_list_chunk()

    def _fill_list_chunk(self) -> None:
        if self._list_fill_restart:
            self._list_filling = False
            self._begin_list_fill(self._list_fill_select)
            return
        samples = self._list_fill_samples
        start = self._list_fill_row
        end = min(start + 20, len(samples))
        self.list_widget.setUpdatesEnabled(False)
        self.list_widget.blockSignals(True)
        try:
            for row in range(start, end):
                self._style_list_row(row, samples[row])
        finally:
            self.list_widget.blockSignals(False)
            self.list_widget.setUpdatesEnabled(True)
        self._list_fill_row = end
        if end < len(samples):
            QTimer.singleShot(0, self._fill_list_chunk)
            return
        self._finish_list_fill()

    def _finish_list_fill(self) -> None:
        selected = self._list_fill_selected
        prev_current = self._list_fill_prev
        scroll = self._list_fill_scroll
        moved_row = None
        self.list_widget.blockSignals(True)
        try:
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
        finally:
            self.list_widget.blockSignals(False)
        if moved_row is None:
            self.list_widget.verticalScrollBar().setValue(scroll)
        else:
            item = self.list_widget.item(moved_row, 0)
            if item is not None:
                self.list_widget.scrollToItem(item)
        self._list_filling = False
        if self._list_fill_restart:
            self._begin_list_fill(self._list_fill_select)
            return
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
                item = self.list_widget.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.list_widget.setItem(row, col, item)
                item.setText(text)
                item.setForeground(color)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setData(Qt.ItemDataRole.UserRole, sample.id)
                item.setFlags(
                    item.flags()
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsEditable
                )
                continue
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
        registered = self._circle_name_text(sample)
        skill_name = self._skill_registered.get(sample.id, "")
        if registered:
            name = f"{registered}  {name}"
        if skill_name:
            name = f"SKILL  {skill_name}  {name}"
        elif skipped and not registered:
            name = f"使わない  {name}"
        name_item.setText(name)
        if registered:
            name_item.setForeground(QColor("#3DDC97"))
        elif self._file_has_tsum_name(sample.source_name):
            name_item.setForeground(QColor("#ff5c5c"))
        elif skipped and not skill_name:
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
        self.train_btn.setEnabled(bool(self._trainable_jobs(self._file_tsum)) and self.train_worker is None)
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
        self.spin_group.setEnabled(is_tsum_kind(self._active_key))
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
        self.predict_btn.setEnabled(has_sample)
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
        if getattr(self, "_elsa_list", False):
            item = self.list_widget.item(current_row, 0)
            raw = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if raw:
                self._show_elsa_file(Path(str(raw)))
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
        self._apply_sample_hint()
        self.update_stats()

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
        first = self.region_list.item(0)
        last = self.region_list.item(rows - 1)
        if first is not None and last is not None:
            top = self.region_list.visualItemRect(first).top()
            bottom = self.region_list.visualItemRect(last).bottom()
            if bottom > top:
                frame = self.region_list.frameWidth() * 2
                self.region_list.setFixedHeight(bottom - top + 1 + frame + 8)
                return
        row_h = 0
        for row in range(rows):
            row_h = max(row_h, self.region_list.sizeHintForRow(row))
        row_h = max(row_h, self.region_list.fontMetrics().height() + 16)
        frame = self.region_list.frameWidth() * 2
        self.region_list.setFixedHeight(rows * row_h + frame + 8)

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
        if not getattr(self, "_keep_list_focus", False):
            self.canvas.setFocus()
        self._apply_visible_keys()
        self._set_dirty(False)
        self._refresh_region_list()
        self._apply_sample_hint(sample)
        self._refresh_group_strip()
        self._load_circle_name_fields()
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
            elif getattr(self, "_skip_auto_predict", False):
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

    def toggle_elsa_list(self) -> None:
        if self._block_if_training():
            return
        self._elsa_list = not getattr(self, "_elsa_list", False)
        self._apply_elsa_chrome()
        self.canvas.set_guide_hidden(self._elsa_list)
        if not self._elsa_list:
            self.refresh_list(self.current_id)
            if self.current_id:
                self.show_sample(self.current_id)
            self.statusBar().showMessage("画像一覧に戻しました", 3000)
            return
        self._fill_elsa_list()

    def _apply_elsa_chrome(self) -> None:
        on = getattr(self, "_elsa_list", False)
        self.stats_label.setVisible(not on)
        self.stats_hint.setVisible(not on)
        self.show_unused_chk.setVisible(not on)
        for name in self._stats_names:
            cell = name.parentWidget()
            if cell is not None:
                cell.setVisible(not on)
        self.elsa_run_btn.setVisible(on)
        self.elsa_delete_btn.setVisible(on)

    def _elsa_skill_dir(self) -> Path:
        return SKILLS_IMAGES_DIR / "Coronation_Elsa"

    def _elsa_files(self) -> list[Path]:
        folder = self._elsa_skill_dir()
        folder.mkdir(parents=True, exist_ok=True)
        return sorted(
            (
                path
                for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
            ),
            key=lambda path: path.name.casefold(),
        )

    def _fill_elsa_list(self, select: Path | None = None) -> None:
        files = self._elsa_files()
        chosen = next((path for path in files if select is not None and path == select), None)
        if chosen is None and files:
            chosen = files[0]
        self._list_filling = False
        self._list_fill_restart = False
        self._sync_list_columns()
        keys = self._list_status_keys()
        self.list_widget.blockSignals(True)
        self.list_widget.setRowCount(len(files))
        for row, path in enumerate(files):
            for col in range(len(keys)):
                item = self.list_widget.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.list_widget.setItem(row, col, item)
                item.setText("")
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                item.setFlags(
                    (item.flags() | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                    & ~Qt.ItemFlag.ItemIsEditable
                )
            name_item = self.list_widget.item(row, len(keys))
            if name_item is None:
                name_item = QTableWidgetItem()
                self.list_widget.setItem(row, len(keys), name_item)
            name_item.setText(path.name)
            name_item.setForeground(QColor("#c5cad3"))
            name_item.setData(Qt.ItemDataRole.UserRole, str(path))
            name_item.setToolTip(str(path))
            name_item.setFlags(
                (name_item.flags() | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                & ~Qt.ItemFlag.ItemIsEditable
            )
        if chosen is not None:
            self.list_widget.setCurrentCell(files.index(chosen), 0)
        self.list_widget.blockSignals(False)
        self.statusBar().showMessage(f"エルサのスキル画像 {len(files)} 枚", 4000)
        if chosen is not None:
            self._show_elsa_file(chosen)
        else:
            self.current_id = None
            self.canvas.clear_image()
            self._set_dirty(False)

    def delete_elsa_image(self) -> None:
        if self._block_if_training() or not getattr(self, "_elsa_list", False):
            return
        row = self.list_widget.currentRow()
        item = self.list_widget.item(row, 0) if row >= 0 else None
        raw = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not raw:
            self.statusBar().showMessage("削除する画像がありません", 3000)
            return
        path = Path(str(raw))
        folder = self._elsa_skill_dir().resolve()
        try:
            resolved = path.resolve()
        except OSError:
            self.statusBar().showMessage("削除する画像がありません", 3000)
            return
        if resolved.parent != folder or not resolved.is_file():
            self.statusBar().showMessage("削除する画像がありません", 3000)
            return
        answer = QMessageBox.question(self, "削除", f"{resolved.name} を削除しますか？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        files = self._elsa_files()
        index = next((i for i, item_path in enumerate(files) if item_path.resolve() == resolved), -1)
        neighbor = None
        if index >= 0 and index + 1 < len(files):
            neighbor = files[index + 1]
        elif index > 0:
            neighbor = files[index - 1]
        self.canvas.clear_image()
        try:
            resolved.unlink()
        except OSError as exc:
            QMessageBox.warning(self, "削除できませんでした", str(exc))
            self._show_elsa_file(resolved)
            return
        self._fill_elsa_list(select=neighbor)
        self.statusBar().showMessage(f"{resolved.name} を削除しました", 4000)

    def _show_elsa_file(self, path: Path) -> None:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.statusBar().showMessage("画像を開けませんでした", 3000)
            return
        self.current_id = None
        self._elsa_path = path
        self.canvas.set_guide_hidden(True)
        self.canvas.set_image(
            pixmap,
            None,
            "unlabeled",
            regions={},
            active_key=self._active_key,
            pieces=[],
        )
        self._set_dirty(False)
        self._refresh_region_list()
        self.statusBar().showMessage(path.name, 3000)

    def run_elsa(self) -> None:
        if self._block_if_training() or not getattr(self, "_elsa_list", False):
            return
        path = getattr(self, "_elsa_path", None)
        pixmap = self.canvas.source_pixmap()
        if path is None or pixmap is None or pixmap.isNull():
            self.statusBar().showMessage("画像がありません", 3000)
            return
        if self.predictor.piece_model is None and not self._ensure_predictor():
            self.statusBar().showMessage("ツムのモデルがありません", 4000)
            return
        if self.predictor.piece_model is None:
            self.statusBar().showMessage("ツムのモデルがありません", 4000)
            return
        self.statusBar().showMessage("種類を分けています")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            from PIL import Image

            with Image.open(path) as image:
                rgb = image.convert("RGB")
            game = self.predictor.predict_all(path, rgb).get("game")
            pieces = self.predictor.predict_pieces(path, game, rgb=rgb)
            lines = elsa_three_chains(pieces, game)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "RUNできませんでした", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.canvas.set_run_mark(pieces, lines)
        self.statusBar().showMessage(f"ツム {sum(1 for piece in pieces if str(piece.get('kind')) != 'bomb')} 個、3チェーン {len(lines)} 本", 4000)

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
            self._group_window.tsumsClearRequested.connect(self._clear_listed_tsums)
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

    def _clear_listed_tsums(self) -> None:
        if not self.current_id:
            return
        self.canvas.clear_pieces_of_kind("tsum")
        self.dataset.clear_named_region(self.current_id, "tsum")
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
        self.statusBar().showMessage("「ツム」を消しました", 3000)

    def on_group_changed(self, value: int) -> None:
        self.canvas.set_piece_group(value)
        self._load_circle_name_fields()

    def trace_chain_candidate(self, index: int) -> None:
        if not self.canvas.start_chain_trace(index):
            self.statusBar().showMessage("つなげられるチェーンがありません", 3000)

    def on_piece_group_changed(self, value: int) -> None:
        self.spin_group.blockSignals(True)
        self.spin_group.setValue(value)
        self.spin_group.blockSignals(False)
        self._load_circle_name_fields()

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
        removed = self._removed_piece_kinds()
        ready = [
            key
            for key in keys
            if self._key_has_content(key) or (is_piece_key(key) and key in removed)
        ]
        scene_ready = [key for key in ready if is_scene_key(key)]
        if len(scene_ready) > 1:
            keep = self._active_key if self._active_key in scene_ready else scene_ready[0]
            ready = [key for key in ready if not is_scene_key(key) or key == keep]
        missing = [key for key in keys if key not in ready and key not in removed]
        if not ready and not removed:
            names = "、".join(PLACE_LABELS.get(key, key) for key in keys)
            QMessageBox.information(self, "まだありません", f"選んだ「{names}」に、まだ枠や〇がありません。")
            return False
        if any(is_piece_key(key) for key in ready) and "game" not in self.canvas.all_region_boxes():
            QMessageBox.information(self, "ゲーム範囲がありません", "ツムとボムにはゲーム範囲が必要です。先にゲーム範囲を囲んでください。")
            return False
        if not any(self._key_needs_save(key) for key in ready) and not removed:
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
        for key in removed:
            if key in ready:
                continue
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
        if hasattr(self, "delete_unsaved_btn"):
            self.delete_unsaved_btn.setEnabled(bool(self._unsaved_samples()))

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

    def _unsaved_samples(self) -> list[Sample]:
        registered = self._skill_registered or registered_skills_by_sample()
        found: list[Sample] = []
        for sample in self.dataset.all():
            if sample.confirmed:
                continue
            if registered.get(sample.id):
                continue
            found.append(sample)
        return found

    def delete_unsaved_images(self) -> None:
        if self._block_if_training():
            return
        self._skill_registered = registered_skills_by_sample()
        unsaved = self._unsaved_samples()
        if not unsaved:
            QMessageBox.information(self, "保存していない画像", "保存していない画像はありません。")
            return
        answer = QMessageBox.question(
            self,
            "保存していない画像を消す",
            f"予測だけ・未設定の {len(unsaved)} 枚をデータセットから削除しますか？\n保存済みとSKILL登録済みは残します。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        current_gone = self.current_id in {sample.id for sample in unsaved} if self.current_id else False
        self.dataset.remove_many([sample.id for sample in unsaved])
        if current_gone:
            self.current_id = None
            self.canvas.clear_image()
            self._set_dirty(False)
        next_id = self.current_id or (self._visible_samples()[0].id if self._visible_samples() else None)
        self.refresh_list(select_id=next_id)
        if next_id and next_id != self.current_id:
            self.show_sample(next_id)
        self.statusBar().showMessage(f"保存していない画像を {len(unsaved)} 枚消しました", 4000)

    def _data_sync(self):
        analyze = str(DATA_SYNC_PATH.parents[2] / "tsumtsum-analyze")
        if analyze not in sys.path:
            sys.path.insert(0, analyze)
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

    def _models_to_upload(self) -> list[Path]:
        return sorted(
            path for path in self.dataset.models_dir.glob("*.pt") if path.is_file()
        )

    def upload_data_to_server(self) -> None:
        if self._block_if_training():
            return
        models = self._models_to_upload()
        if not models:
            QMessageBox.warning(self, "モデルがありません", "送るモデルがありません。")
            return
        names = "、".join(path.name for path in models)
        answer = QMessageBox.question(
            self,
            "サーバーに保存",
            "次のモデルを http://hokkai-syabusyabu.com/home_page/workshop/models に保存します。続けますか？\n"
            + names,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        sync = self._server_sync()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            sync.run_with_progress(
                self,
                "サーバーに保存しています",
                lambda progress: self._upload_models(sync, models, progress),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "保存できませんでした", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "サーバーに保存しました", f"{names} を保存しました。")

    def _upload_models(self, sync, models: list[Path], progress) -> None:
        total = len(models)
        for index, model in enumerate(models):
            progress(index, total, model.name)
            sync.upload_model(model)
        progress(total, total, models[-1].name)

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
        self.predictor.reload(pump=QApplication.processEvents, device="cpu")
        self._remember_last_boxes()
        self.refresh_list()
        self.statusBar().showMessage("dataを取り込みました", 5000)

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
        if self._coin_worker is not None and self._coin_worker.isRunning():
            return
        self._ensure_predictor()
        predict = (
            (lambda crop, box_key=key: self.predictor.predict_coin_digits(crop, box_key))
            if self.predictor.digit_model
            else None
        )
        image_path = sample.image_path
        sample_id = self.current_id

        def work():
            found: list[str] = []
            crop = None
            error = ""
            for _ in range(5):
                try:
                    crop, number = ocr_coin_number(image_path, box, predict_fn=predict)
                except Exception as exc:  # noqa: BLE001
                    error = str(exc)
                    continue
                if number:
                    found.append(number)
            number = max(set(found), key=found.count) if found else ""
            return sample_id, key, crop, number, error

        self.read_coin_btn.setEnabled(False)
        self.statusBar().showMessage("コインの数字を読んでいます")
        worker = CoinReadWorker(work)
        worker.finished_ok.connect(self._on_coin_read_finished)
        worker.failed.connect(self._on_coin_read_failed)
        self._coin_worker = worker
        worker.start()

    def _on_coin_read_finished(self, result) -> None:
        self._coin_worker = None
        self.read_coin_btn.setEnabled(self.current_id is not None)
        sample_id, key, crop, number, error = result
        if crop is None:
            QMessageBox.warning(self, "数字を取れませんでした", error or "数字を取れませんでした")
            return
        if sample_id != self.current_id:
            return
        dialog = CoinNumberDialog(crop, number, self)
        dialog.exec()
        if dialog.taught and dialog.number():
            self.dataset.set_reading(self.current_id, key, dialog.number())
            self.refresh_list(select_id=self.current_id)
            self.statusBar().showMessage(f"コイン {dialog.number()} を教えました。学習すると次から使います", 5000)
        elif dialog.number():
            self.statusBar().showMessage(f"コイン {dialog.number()}", 5000)

    def _on_coin_read_failed(self, message: str) -> None:
        self._coin_worker = None
        self.read_coin_btn.setEnabled(self.current_id is not None)
        QMessageBox.warning(self, "数字を取れませんでした", message)

    def _coin_read_key(self, boxes: dict[str, dict[str, int]] | None = None) -> str | None:
        boxes = boxes if boxes is not None else self.canvas.all_region_boxes()
        if is_coin_box_key(self._active_key) and self._active_key in boxes:
            return self._active_key
        for key in COIN_BOX_KEYS:
            if key in boxes:
                return key
        return None

    def predict_current(self) -> None:
        if not self.current_id:
            return
        if self._block_if_training():
            return
        if self._predict_worker is not None and self._predict_worker.isRunning():
            return
        sample_id = self.current_id
        self.predict_btn.setEnabled(False)
        self.statusBar().showMessage("予測しています")
        worker = PredictWorker(lambda: self._predict_work(sample_id))
        worker.finished_ok.connect(self._on_predict_finished)
        worker.failed.connect(self._on_predict_failed)
        self._predict_worker = worker
        worker.start()

    def _predict_work(self, sample_id: str) -> tuple[str, list[str]]:
        if not self.predictor.is_ready():
            self.predictor.reload(pump=None, device="cpu")
        if not self.predictor.is_ready():
            raise RuntimeError("モデルがありません。範囲を教えてから学習してください。")
        sample = self.dataset.get(sample_id)
        if sample is None:
            raise RuntimeError("画像がありません")
        return sample_id, self._predict_into_sample(sample)

    def _on_predict_finished(self, sample_id: str, added: list) -> None:
        self._predict_worker = None
        self.refresh_list(select_id=self.current_id or sample_id)
        if sample_id == self.current_id:
            self.show_sample(sample_id)
        if added:
            names = "、".join(PLACE_LABELS.get(key, key) for key in added)
            self.statusBar().showMessage(f"予測を入れました: {names}。合っていれば保存してください", 4000)
        else:
            self.statusBar().showMessage("保存済みの場所はそのままです。足りない場所はありませんでした", 4000)
        self.update_stats()

    def _on_predict_failed(self, message: str) -> None:
        self._predict_worker = None
        self.update_stats()
        if "モデルがありません" in message:
            QMessageBox.information(self, "予測", message)
            return
        QMessageBox.warning(self, "予測に失敗", message)

    def _used_tsum_choices(self) -> list[tuple[str, str]]:
        if not USE_TSUM_REGISTRY.is_file():
            return []
        try:
            payload = json.loads(USE_TSUM_REGISTRY.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(payload, dict):
            return []
        rows = [
            (str(key), str(value))
            for key, value in payload.items()
            if str(key).strip() and str(value).strip()
        ]
        return sorted(rows, key=lambda row: row[1].casefold())

    def _set_place_tools_visible(self, visible: bool) -> None:
        for widget in (
            self.read_coin_btn,
            self.open_result_train_btn,
            self.model_label,
            self.progress,
            self.server_save_btn,
            self.shortcut_btn,
            self.elsa_list_btn,
        ):
            widget.setVisible(visible)
        if visible:
            self.progress.setVisible(False)

    def _toggle_name_mode(self, on: bool) -> None:
        self.name_mode_btn.setText("今までの画面" if on else "ツム名を登録")
        self.name_panel.setVisible(on)
        self.tsum_select_btn.setVisible(not on)
        if on:
            self.tsum_pick_row.hide()
            self.tsum_name_list.hide()
            self._set_place_tools_visible(False)
            self._load_circle_name_fields()
            self._refresh_saved_names()
            self._name_window.show()
            self._name_window.raise_()
            self._name_window.activateWindow()
            return
        self._name_window.hide()
        self.region_list.show()
        self._set_place_tools_visible(True)

    def _load_circle_name_fields(self) -> None:
        sample = self.dataset.get(self.current_id) if self.current_id else None
        saved: dict[str, str] = {}
        if sample is not None:
            saved = sample.circle_names.get(str(int(self.spin_group.value()))) or {}
        self.name_ja.setText(str(saved.get("ja") or ""))
        self.name_en.setText(str(saved.get("en") or ""))
        self._show_name_state(sample, int(self.spin_group.value()))
        self._fill_name_faces(sample, str(int(self.spin_group.value())))
        if sample is not None:
            self.canvas.set_circle_names(sample.circle_names)

    def _register_circle_name(self) -> None:
        sample = self.dataset.get(self.current_id) if self.current_id else None
        if sample is None:
            self.statusBar().showMessage("画像がありません", 4000)
            return
        group = int(self.spin_group.value())
        has = any(
            is_tsum_kind(str(piece.get("kind") or "")) and int(piece.get("group") or 1) == group
            for piece in self.canvas.all_pieces()
        )
        if not has:
            self.statusBar().showMessage(f"No. {group} の〇がありません", 4000)
            return
        ja = self.name_ja.text().strip()
        en = self.name_en.text().strip()
        if not ja or not en:
            self.statusBar().showMessage("日本語と英語を入れてください", 4000)
            return
        names = dict(sample.circle_names)
        prev = names.get(str(group)) or {}
        entry: dict = {"ja": ja, "en": en}
        raw_out = prev.get("out")
        if isinstance(raw_out, list) and raw_out:
            entry["out"] = [str(item) for item in raw_out]
        names[str(group)] = entry
        sample.circle_names = names
        self.dataset.save()
        self.canvas.set_circle_names(sample.circle_names)
        self._show_name_state(sample, group)
        self._fill_name_faces(sample, str(group))
        self._refresh_saved_names()
        self._restyle_sample_row(sample.id)
        self.statusBar().showMessage(f"No. {group}  {ja}  {en}", 4000)

    def _show_name_state(self, sample: Sample | None, group: int) -> None:
        saved: dict[str, str] = {}
        if sample is not None:
            saved = sample.circle_names.get(str(group)) or {}
        ja = str(saved.get("ja") or "").strip()
        en = str(saved.get("en") or "").strip()
        if ja or en:
            self.name_state.setText(f"No.{group}  登録済み  {ja}  {en}".strip())
            self.name_state.setStyleSheet("color: #3DDC97;")
            return
        self.name_state.setText(f"No.{group}  未登録")
        self.name_state.setStyleSheet("color: #8b93a0;")

    def _sample_board(self, sample: Sample) -> QPixmap | None:
        if sample.id == self.current_id:
            pixmap = self.canvas.source_pixmap()
            if pixmap is not None and not pixmap.isNull():
                return pixmap
        pixmap = QPixmap(str(sample.image_path))
        if pixmap.isNull():
            return None
        return pixmap

    def _group_pieces(self, sample: Sample, group: str) -> list[dict]:
        source = self.canvas.all_pieces() if sample.id == self.current_id else sample.pieces
        return [
            piece
            for piece in source
            if is_tsum_kind(str(piece.get("kind") or "")) and str(int(piece.get("group") or 1)) == str(group)
        ]

    def _piece_face(self, pixmap: QPixmap, piece: dict, size: int = 52) -> QPixmap:
        x, y = int(piece["x"]), int(piece["y"])
        radius = max(8, int(piece.get("r") or 16))
        span = max(12, int(round(radius * 1.05)))
        tile = pixmap.copy(QRect(x - span, y - span, span * 2, span * 2))
        if tile.isNull():
            return QPixmap()
        return tile.scaled(
            size,
            size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _clear_grid(self, layout: QGridLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _fill_name_faces(self, sample: Sample | None, group: str) -> None:
        self._clear_grid(self.name_faces_layout)
        if sample is None:
            self.name_faces.hide()
            return
        pixmap = self._sample_board(sample)
        pieces = self._group_pieces(sample, group)
        if pixmap is None or not pieces:
            self.name_faces.hide()
            return
        for index, piece in enumerate(pieces):
            face = self._piece_face(pixmap, piece)
            if face.isNull():
                continue
            label = QLabel()
            label.setPixmap(face)
            label.setFixedSize(face.size())
            self.name_faces_layout.addWidget(label, index // 4, index % 4)
        self.name_faces.setVisible(self.name_faces_layout.count() > 0)

    def _circle_name_text(self, sample: Sample) -> str:
        names = getattr(sample, "circle_names", None) or {}
        parts: list[str] = []
        for key in sorted(names, key=lambda item: int(item) if str(item).isdigit() else 0):
            value = names[key] or {}
            ja = str(value.get("ja") or "").strip()
            en = str(value.get("en") or "").strip()
            if ja or en:
                parts.append(f"No.{key} {ja} {en}".strip())
        return "  ".join(parts)

    def _refresh_saved_names(self) -> None:
        current = self.current_id
        current_saved: dict[str, str] = {}
        if current:
            current_sample = self.dataset.get(current)
            if current_sample is not None:
                current_saved = current_sample.circle_names.get(str(int(self.spin_group.value()))) or {}
        current_ja = str(current_saved.get("ja") or "").strip()
        current_en = str(current_saved.get("en") or "").strip()
        grouped: dict[tuple[str, str], list[tuple[Sample, str]]] = {}
        for sample in self.dataset.all():
            names = getattr(sample, "circle_names", None) or {}
            for key in sorted(names, key=lambda item: int(item) if str(item).isdigit() else 0):
                value = names[key] or {}
                ja = str(value.get("ja") or "").strip()
                en = str(value.get("en") or "").strip()
                if not ja and not en:
                    continue
                grouped.setdefault((ja, en), []).append((sample, str(key)))
        self.name_saved_list.clear()
        select = -1
        for (ja, en), rows in grouped.items():
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(4, 4, 4, 4)
            row_layout.setSpacing(4)
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(4)
            face_count = 0
            for sample, key in rows:
                pixmap = self._sample_board(sample)
                if pixmap is None:
                    continue
                skipped = self._named_out(sample, key)
                for piece in self._group_pieces(sample, key):
                    spot = f"{int(piece['x'])},{int(piece['y'])}"
                    if spot in skipped:
                        continue
                    face = self._piece_face(pixmap, piece, 44)
                    if face.isNull():
                        continue
                    label = _NamedFace(
                        face,
                        lambda sid=sample.id, g=key, x=int(piece["x"]), y=int(piece["y"]): self._exclude_named_piece(
                            sid, g, x, y
                        ),
                    )
                    grid.addWidget(label, face_count // 4, face_count % 4)
                    face_count += 1
            caption = _ClickLabel(
                f"{ja}  {en}  {face_count}個".strip(),
                lambda name_ja=ja, name_en=en: self._pick_saved_name(name_ja, name_en),
            )
            row_layout.addWidget(caption)
            if grid.count():
                row_layout.addLayout(grid)
            row.adjustSize()
            face_rows = (face_count + 3) // 4 if face_count else 0
            height = 8 + face_rows * 48 + caption.sizeHint().height() + 8
            hint = row.sizeHint()
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, ja)
            item.setData(Qt.ItemDataRole.UserRole + 1, en)
            item.setToolTip(f"{ja}  {en}  {face_count}個".strip())
            item.setSizeHint(QSize(220, max(hint.height(), height)))
            self.name_saved_list.addItem(item)
            self.name_saved_list.setItemWidget(item, row)
            if ja == current_ja and en == current_en and (current_ja or current_en):
                select = self.name_saved_list.count() - 1
        if select >= 0:
            self.name_saved_list.setCurrentRow(select)

    def _named_out(self, sample: Sample, group: str) -> set[str]:
        saved = (sample.circle_names or {}).get(str(group)) or {}
        raw = saved.get("out")
        if not isinstance(raw, list):
            return set()
        return {str(item) for item in raw}

    def _exclude_named_piece(self, sample_id: str, group: str, x: int, y: int) -> None:
        sample = self.dataset.get(sample_id)
        if sample is None:
            return
        names = dict(sample.circle_names)
        saved = dict(names.get(str(group)) or {})
        spot = f"{int(x)},{int(y)}"
        out = [str(item) for item in saved.get("out") or []]
        if spot not in out:
            out.append(spot)
        saved["out"] = out
        names[str(group)] = saved
        sample.circle_names = names
        self.dataset.save()
        self._refresh_saved_names()
        if sample_id == self.current_id:
            self._fill_name_faces(sample, str(group))
        ja = str(saved.get("ja") or "").strip()
        en = str(saved.get("en") or "").strip()
        self.statusBar().showMessage(f"除外しました  {ja}  {en}".strip(), 4000)

    def _existing_circle_name(self, field: str, text: str) -> tuple[str, str] | None:
        query = text.strip()
        if not query:
            return None
        folded = query.casefold()
        for sample in self.dataset.all():
            names = getattr(sample, "circle_names", None) or {}
            for value in names.values():
                ja = str(value.get("ja") or "").strip()
                en = str(value.get("en") or "").strip()
                if field == "ja" and ja and ja.casefold() == folded:
                    return ja, en
                if field == "en" and en and en.casefold() == folded:
                    return ja, en
        return None

    def _show_existing_name(self, field: str, text: str) -> None:
        if getattr(self, "_name_lookup_lock", False):
            return
        found = self._existing_circle_name(field, text)
        if found is None:
            return
        ja, en = found
        self._name_lookup_lock = True
        try:
            if ja and self.name_ja.text().strip() != ja:
                self.name_ja.setText(ja)
            if en and self.name_en.text().strip() != en:
                self.name_en.setText(en)
        finally:
            self._name_lookup_lock = False
        for row in range(self.name_saved_list.count()):
            item = self.name_saved_list.item(row)
            if item is None:
                continue
            saved_ja = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            saved_en = str(item.data(Qt.ItemDataRole.UserRole + 1) or "").strip()
            if saved_ja == ja and saved_en == en:
                self.name_saved_list.setCurrentRow(row)
                self.name_saved_list.scrollToItem(item)
                self._name_window.show()
                self._name_window.raise_()
                return

    def _pick_saved_name(self, ja: str, en: str) -> None:
        if not ja and not en:
            return
        self._name_lookup_lock = True
        try:
            self.name_ja.setText(ja)
            self.name_en.setText(en)
        finally:
            self._name_lookup_lock = False

    def _open_saved_circle_name(self, item: QListWidgetItem) -> None:
        ja = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        en = str(item.data(Qt.ItemDataRole.UserRole + 1) or "").strip()
        self._pick_saved_name(ja, en)

    def _restyle_sample_row(self, sample_id: str) -> None:
        sample = self.dataset.get(sample_id)
        if sample is None:
            return
        for row in range(self.list_widget.rowCount()):
            item = self.list_widget.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == sample_id:
                self._style_list_row(row, sample)
                return

    def _select_sample_row(self, sample_id: str) -> None:
        for row in range(self.list_widget.rowCount()):
            item = self.list_widget.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == sample_id:
                self.list_widget.setCurrentCell(row, 0)
                self.list_widget.scrollToItem(item)
                return
        self.show_sample(sample_id)

    def show_tsum_list(self) -> None:
        if self.tsum_name_list.isVisible():
            self.tsum_pick_row.hide()
            self.tsum_name_list.hide()
            self._set_place_tools_visible(True)
            return
        choices = self._used_tsum_choices()
        self.tsum_name_list.clear()
        for folder, shown in choices:
            item = QListWidgetItem(shown)
            item.setData(Qt.ItemDataRole.UserRole, folder)
            self.tsum_name_list.addItem(item)
        if self.tsum_name_list.count():
            self.tsum_name_list.setCurrentRow(0)
        self.tsum_pick_row.show()
        self.tsum_name_list.show()
        self._fit_name_list(self.tsum_name_list)
        self._set_place_tools_visible(False)
        if not choices:
            self.statusBar().showMessage("使用ツムがありません", 4000)

    def on_tsum_name_clicked(self, item: QListWidgetItem) -> None:
        folder = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not folder:
            return
        self._apply_file_tsum(folder, item.text())

    def _tsum_name_tokens(self) -> list[str]:
        tokens = getattr(self, "_tsum_name_token_cache", None)
        if tokens is None:
            tokens = sorted(
                {token for folder, name in self._used_tsum_choices() for token in (folder, name) if token},
                key=len,
                reverse=True,
            )
            self._tsum_name_token_cache = tokens
        return tokens

    def _specified_tsum_folder(self, sample) -> str:
        names = [
            str(getattr(sample, "source_name", "") or ""),
            str(getattr(sample, "image", "") or ""),
        ]
        pairs: list[tuple[str, str]] = []
        for folder, shown in self._used_tsum_choices():
            for token in (folder, shown):
                key = str(token or "").strip()
                if key:
                    pairs.append((key.casefold(), folder))
        pairs.sort(key=lambda item: len(item[0]), reverse=True)
        for name in names:
            folded = name.casefold()
            for key, folder in pairs:
                if folded.startswith(key + "_") or folded.startswith(key + " "):
                    return folder
        return ""

    def _file_has_tsum_name(self, source_name: str) -> bool:
        folded = (source_name or "").casefold()
        for token in self._tsum_name_tokens():
            key = token.casefold()
            if folded.startswith(key + "_") or folded.startswith(key + " "):
                return True
        return False

    def _source_name_for_tsum(self, source_name: str, shown: str) -> str:
        text = source_name or ""
        stem, suffix = text, ""
        if "." in text and not text.endswith("."):
            stem, ext = text.rsplit(".", 1)
            suffix = "." + ext
        tokens = sorted(
            {token for folder, name in self._used_tsum_choices() for token in (folder, name) if token},
            key=len,
            reverse=True,
        )
        changed = True
        while changed:
            changed = False
            folded = stem.casefold()
            for token in tokens:
                key = token.casefold()
                for sep in ("_", " "):
                    prefix = key + sep
                    if folded.startswith(prefix):
                        stem = stem[len(prefix) :]
                        changed = True
                        break
                if changed:
                    break
        stem = stem.strip(" _") or "image"
        return f"{shown}_{stem}{suffix}"

    def _on_file_name_double_clicked(self, item: QTableWidgetItem) -> None:
        if item.column() != self.list_widget.columnCount() - 1:
            return
        if self._block_if_training():
            return
        sample_id = self._list_id_at(item.row())
        if not sample_id:
            return
        chosen = self._choose_used_tsum("どの使用ツムですか？")
        if chosen is None:
            return
        folder, shown = chosen
        self._specify_file_tsum(sample_id, folder, shown)

    def _specify_file_tsum(self, sample_id: str, folder: str, shown: str) -> None:
        sample = self.dataset.get(sample_id)
        if sample is None:
            return
        renamed = self._source_name_for_tsum(sample.source_name, folder)
        if renamed != sample.source_name:
            sample.source_name = renamed
            self.dataset.save()
        self.refresh_list(sample_id)
        self.statusBar().showMessage(f"{shown} を指定しました", 4000)

    def _fit_name_list(self, widget: QListWidget) -> None:
        rows = widget.count()
        if rows <= 0:
            return
        row_h = widget.fontMetrics().height() + 16
        for row in range(rows):
            row_h = max(row_h, widget.sizeHintForRow(row))
        frame = widget.frameWidth() * 2
        widget.setFixedHeight(rows * row_h + frame + 8)

    def _restore_file_list(self) -> None:
        self._file_tsum = None
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._refresh_file_view()
        count = len(self._ordered_visible_samples())
        self.statusBar().showMessage(f"ファイル一覧を戻しました  {count} 枚", 4000)

    def _refresh_file_view(self) -> None:
        if getattr(self, "_elsa_list", False):
            self._elsa_list = False
            self._apply_elsa_chrome()
            self.canvas.set_guide_hidden(False)
        samples = self._ordered_visible_samples()
        select = (
            self.current_id
            if any(sample.id == self.current_id for sample in samples)
            else (samples[0].id if samples else None)
        )
        if select is None:
            self.current_id = None
            self.canvas.clear_image()
            self._set_dirty(False)
        self.refresh_list(select)
        if select and select != self.current_id:
            self.show_sample(select)

    def _apply_file_tsum(self, folder: str, shown: str) -> None:
        self._file_tsum = (folder, shown)
        self._refresh_file_view()
        self.statusBar().showMessage(f"{shown}  {len(self._ordered_visible_samples())} 枚", 4000)

    def _ask_train_used_tsum(self) -> tuple[str, str] | None:
        return self._choose_used_tsum("どの使用ツムを学習しますか？")

    def _choose_used_tsum(self, prompt: str) -> tuple[str, str] | None:
        choices = self._used_tsum_choices()
        if not choices:
            QMessageBox.information(self, "使用ツム", "使用ツムがありません。")
            return None
        dialog = QDialog(self)
        dialog.setWindowTitle("使用ツム")
        dialog.setModal(True)
        dialog.setMinimumWidth(320)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(prompt))
        name_list = QListWidget()
        for folder, shown in choices:
            item = QListWidgetItem(shown)
            item.setData(Qt.ItemDataRole.UserRole, folder)
            name_list.addItem(item)
        name_list.setCurrentRow(0)
        layout.addWidget(name_list, 1)
        buttons = QDialogButtonBox()
        ok_btn = buttons.addButton("これにします", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = buttons.addButton("やめる", QDialogButtonBox.ButtonRole.RejectRole)
        cancel_btn.setAutoDefault(False)
        layout.addWidget(buttons)
        name_list.itemDoubleClicked.connect(lambda *_: dialog.accept())
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        row = name_list.currentItem()
        if row is None:
            return None
        folder = str(row.data(Qt.ItemDataRole.UserRole) or "")
        if not folder:
            return None
        return folder, row.text()

    def _matches_used_tsum(self, sample, folder: str, shown: str) -> bool:
        names = {
            str(getattr(sample, "source_name", "") or ""),
            str(getattr(sample, "image", "") or ""),
        }
        folded = [name.casefold() for name in names if name]
        for token in (shown, folder):
            key = str(token or "").strip()
            if key and any(key.casefold() in name for name in folded):
                return True
        return False

    def _for_used(self, samples, used: tuple[str, str] | None):
        if used is None:
            return list(samples)
        folder, shown = used
        return [sample for sample in samples if self._matches_used_tsum(sample, folder, shown)]

    def _path_for_used(self, key: str, used: tuple[str, str] | None):
        if used is None:
            return self.dataset.model_path_for(key)
        return self.dataset.models_dir / used[0] / model_filename(key)

    def _trainable_jobs(self, used: tuple[str, str] | None = None) -> list[tuple]:
        selected = set(self._selected_place_keys())
        jobs: list[tuple] = []
        for key in REGION_KEYS:
            if key not in selected:
                continue
            samples = self._for_used(self.dataset.labeled_for(key), used)
            if len(samples) >= MIN_TRAIN_SAMPLES:
                jobs.append((key, samples, self._path_for_used(key, used), self._job_label(key)))
        piece_keys = [key for key in PIECE_KEYS if key in selected]
        if piece_keys:
            piece_map = {
                sample.id: sample
                for key in piece_keys
                for sample in self.dataset.labeled_for(key)
            }
            piece_samples = self._for_used(piece_map.values(), used)
            if "tsum" in piece_keys or "big" in piece_keys:
                type_samples = [
                    sample
                    for sample in piece_samples
                    if len(
                        {
                            int(piece.get("group") or 1)
                            for piece in sample.pieces
                            if is_tsum_kind(str(piece.get("kind") or ""))
                        }
                    )
                    >= 2
                ]
                if used is not None and len(type_samples) >= MIN_TRAIN_SAMPLES:
                    folder, shown = used
                    jobs.append(
                        (
                            "tsum_types",
                            type_samples,
                            self.dataset.models_dir / folder / "tsum_types.pt",
                            f"ツムの種類 {shown}",
                        )
                    )
            if len(piece_samples) >= MIN_TRAIN_SAMPLES:
                jobs.append(
                    (
                        "pieces",
                        piece_samples,
                        self._path_for_used("pieces", used),
                        self._piece_job_label(piece_keys),
                    )
                )
        if set(selected) & set(COIN_BOX_KEYS):
            digit_samples = self._for_used(self.dataset.labeled_digit_samples(), used)
            if len(digit_samples) >= MIN_TRAIN_SAMPLES:
                jobs.append(
                    (
                        "coin_digits",
                        digit_samples,
                        self._path_for_used("coin_digits", used),
                        "コインの数字",
                    )
                )
        scene_selected = [key for key in SCENE_KEYS if key in selected]
        if scene_selected:
            playable = self._for_used(
                [sample for sample in self.dataset.all() if sample.status != "skipped"],
                used,
            )
            others = self._scene_other_count(used)
            if (
                all(
                    len(self._for_used(self.dataset.labeled_for(key), used)) >= MIN_TRAIN_SAMPLES
                    for key in scene_selected
                )
                and others >= MIN_TRAIN_SAMPLES
            ):
                jobs.append(
                    (
                        "scene",
                        playable,
                        self._path_for_used("scene", used),
                        "GO・TIME UP",
                    )
                )
        return jobs

    def _scene_other_count(self, used: tuple[str, str] | None = None) -> int:
        samples = self.dataset.all()
        if used is not None:
            samples = self._for_used(samples, used)
        return sum(
            1
            for sample in samples
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
        if self.list_widget.columnCount() != len(headers):
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

    def _removed_piece_kinds(self) -> list[str]:
        sample = self.dataset.get(self.current_id) if self.current_id else None
        if sample is None:
            return []
        present = {str(piece.get("kind") or "") for piece in self.canvas.all_pieces()}
        return [
            key
            for key in PIECE_KEYS
            if key not in present and any(piece.get("kind") == key for piece in sample.pieces)
        ]

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
                return bool(saved)
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
            self.delete_unsaved_btn,
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
        self.train_shutdown_btn.setEnabled(bool(self._trainable_jobs(self._file_tsum)) and self.train_worker is None)

    def _block_if_training(self) -> bool:
        if not self._is_training():
            return False
        self.statusBar().showMessage("学習中です。終わるまで操作できません", 3000)
        return True

    def _place_train_fx(self) -> None:
        host = self._train_fx.parentWidget() or self
        self._train_fx.setGeometry(0, 0, host.width(), host.height())
        self._train_fx.raise_()

    def _request_canvas_3_2(self) -> None:
        if getattr(self, "_syncing_canvas", False):
            return
        if getattr(self, "_canvas_echo", False):
            return
        timer = getattr(self, "_canvas_sync_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._sync_canvas_3_2)
            self._canvas_sync_timer = timer
        if not timer.isActive():
            timer.start(0)

    def _sync_canvas_3_2(self) -> None:
        if getattr(self, "_syncing_canvas", False):
            return
        col = getattr(self, "_canvas_host", None)
        if col is None or not hasattr(self, "canvas"):
            return
        height = col.height()
        if height < 80:
            return
        last = getattr(self, "_canvas_sync_h", None)
        width = (height * 2) // 3
        same_height = last is not None and abs(height - last) <= 2
        already = (
            col.width() == width
            and col.minimumWidth() == width
            and col.maximumWidth() == width
        )
        if already and (same_height or last is None):
            self._canvas_sync_h = height
            return
        if same_height:
            return
        self._syncing_canvas = True
        col.setFixedWidth(width)
        self._canvas_sync_h = col.height()
        QTimer.singleShot(0, self._end_canvas_sync)

    def _end_canvas_sync(self) -> None:
        col = getattr(self, "_canvas_host", None)
        if col is not None:
            self._canvas_sync_h = col.height()
        self._syncing_canvas = False
        self._canvas_echo = True
        QTimer.singleShot(0, self._clear_canvas_echo)

    def _clear_canvas_echo(self) -> None:
        self._canvas_echo = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_canvas_3_2()
        self._fit_region_list()
        QTimer.singleShot(0, self._fit_region_list)
        if self._data_loaded:
            return
        self._data_loaded = True
        QTimer.singleShot(0, self._load_dataset)

    def _load_dataset(self) -> None:
        self.statusBar().showMessage("画像一覧を読み込み中")
        self.dataset.reload()
        self._remember_last_boxes()
        self.refresh_list()
        self.statusBar().clearMessage()

    def _ensure_predictor(self) -> bool:
        if self.predictor.is_ready():
            return True
        self.statusBar().showMessage("モデルを読み込み中")
        try:
            self.predictor.reload(pump=None, device="cpu")
        except Exception:
            return False
        self.update_stats()
        return self.predictor.is_ready()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        train_fx = hasattr(self, "_train_fx") and self._train_fx.isVisible()
        if getattr(self, "_syncing_canvas", False) or getattr(self, "_canvas_echo", False):
            if train_fx:
                self._place_train_fx()
            return
        col = getattr(self, "_canvas_host", None)
        last = getattr(self, "_canvas_sync_h", None)
        if col is not None and last is not None and abs(col.height() - last) <= 2:
            if train_fx:
                self._place_train_fx()
            return
        if hasattr(self, "canvas"):
            self._request_canvas_3_2()
        if train_fx:
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
        used = None
        if "tsum" in selected or "big" in selected:
            used = self._ask_train_used_tsum()
            if used is None:
                return
        elif self._file_tsum is not None:
            used = self._file_tsum
        jobs = self._trainable_jobs(used)
        counts = self.dataset.labeled_counts()

        def place_count(key: str) -> int:
            if used is None:
                return counts.get(key, 0)
            return len(self._for_used(self.dataset.labeled_for(key), used))

        if not jobs:
            lines = [
                f"チェックした種類の学習には、正解が {MIN_TRAIN_SAMPLES} 枚以上必要です。",
                "",
            ]
            lines.extend(f"{PLACE_LABELS.get(key, key)}: {place_count(key)} 枚" for key in selected)
            if any(key in SCENE_KEYS for key in selected):
                lines.append(f"GO/TIME UP以外: {self._scene_other_count(used)} 枚")
            QMessageBox.information(self, "まだ足りません", "\n".join(lines))
            return
        ready_lines = [f"{job[3]}: {len(job[1])} 枚" for job in jobs]
        trained_keys = {job[0] for job in jobs}
        skipped = []
        for key in selected:
            if key in PIECE_KEYS:
                if "pieces" in trained_keys:
                    continue
                skipped.append(f"{PLACE_LABELS[key]}: {place_count(key)} 枚")
            elif key in SCENE_KEYS:
                if "scene" in trained_keys:
                    continue
                skipped.append(f"{PLACE_LABELS[key]}: {place_count(key)} 枚")
            elif key not in trained_keys:
                skipped.append(f"{PLACE_LABELS.get(key, key)}: {place_count(key)} 枚")
        if set(selected) & set(COIN_BOX_KEYS) and "coin_digits" not in trained_keys:
            digit_count = len(self._for_used(self.dataset.labeled_digit_samples(), used))
            skipped.append(f"コインの数字: {digit_count} 枚")
        if any(key in SCENE_KEYS for key in selected) and "scene" not in trained_keys:
            others = self._scene_other_count(used)
            if others < MIN_TRAIN_SAMPLES:
                skipped.append(f"GO/TIME UP以外: {others} 枚")
        message = "チェックした種類だけ学習します。\n" + "\n".join(ready_lines)
        piece_selected = [key for key in PIECE_KEYS if key in selected]
        if (
            used is None
            and piece_selected
            and "pieces" in trained_keys
            and set(piece_selected) != set(PIECE_KEYS)
        ):
            message += "\n（ツム・ボム・デカツムは同じ〇モデルです。選んだ〇の学習で、〇の予測はまとめて更新されます。）"
        if used is not None and ("tsum" in selected or "big" in selected) and "tsum_types" not in trained_keys:
            type_count = len(
                [
                    sample
                    for sample in self._for_used(self.dataset.labeled_for("tsum"), used)
                    if len(
                        {
                            int(piece.get("group") or 1)
                            for piece in sample.pieces
                            if is_tsum_kind(str(piece.get("kind") or ""))
                        }
                    )
                    >= 2
                ]
            )
            skipped.append(f"ツムの種類 {used[1]}: {type_count} 枚")
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
            self.predictor.reload(pump=QApplication.processEvents, device="cpu")
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
        if not any(is_tsum_kind(str(piece.get("kind") or "")) for piece in sample.pieces):
            return False
        from PIL import Image

        pieces = [dict(piece) for piece in sample.pieces]
        before = [
            (int(piece["x"]), int(piece["y"]), int(piece.get("group") or 1))
            for piece in pieces
            if is_tsum_kind(str(piece.get("kind") or ""))
        ]
        with Image.open(sample.image_path) as image:
            self.predictor._assign_groups(image.convert("RGB"), pieces)
        after = [
            (int(piece["x"]), int(piece["y"]), int(piece.get("group") or 1))
            for piece in pieces
            if is_tsum_kind(str(piece.get("kind") or ""))
        ]
        if before == after:
            return False
        self.dataset.set_pieces(sample.id, pieces)
        return True

    def _predict_into_sample(self, sample: Sample, *, overwrite: bool = True) -> list[str]:
        self.predictor.use_used_tsum_model(self._specified_tsum_folder(sample))
        added: list[str] = []
        boxes = self.predictor.predict_all(sample.image_path)
        if boxes:
            added.extend(self.dataset.apply_predictions(sample.id, boxes))
        sample = self.dataset.get(sample.id) or sample
        game = sample.regions.get("game") or sample.game_region
        existing_tsums = [
            piece for piece in sample.pieces if is_tsum_kind(str(piece.get("kind") or ""))
        ]
        tsum_locked = (not overwrite) and (
            "tsum" in sample.confirmed or "big" in sample.confirmed
        )
        if existing_tsums and not tsum_locked:
            if self._relabel_tsum_groups(sample):
                added.append("tsum")
            sample = self.dataset.get(sample.id) or sample
        pieces = self.predictor.predict_pieces(sample.image_path, game)
        if existing_tsums:
            pieces = [
                piece
                for piece in pieces
                if str(piece.get("kind") or "") != "tsum"
            ]
        replace_empty: tuple[str, ...] = ()
        if overwrite and "big" not in sample.confirmed:
            replace_empty = ("big",)
        if pieces or replace_empty:
            if not overwrite:
                existing = {str(piece.get("kind")) for piece in sample.pieces}
                confirmed = set(sample.confirmed)
                pieces = [
                    piece
                    for piece in pieces
                    if piece.get("kind") not in existing and piece.get("kind") not in confirmed
                ]
            if pieces or replace_empty:
                added.extend(
                    self.dataset.apply_piece_predictions(
                        sample.id,
                        pieces,
                        replace_empty=replace_empty,
                    )
                )
        return added

    def eventFilter(self, watched, event) -> bool:
        if watched is self.canvas and event.type() == QEvent.Type.Resize:
            if hasattr(self, "_train_fx") and self._train_fx.isVisible():
                self._place_train_fx()
        if self._is_training() and watched is self.canvas and event.type() == QEvent.Type.KeyPress:
            return True
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down)
            and event.modifiers()
            in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)
            and (
                watched is self.canvas
                or watched is self.list_widget
                or self.list_widget.isAncestorOf(watched)
            )
        ):
            if getattr(self, "_arrow_nav", False):
                return True
            self._arrow_nav = True
            try:
                from_list = watched is self.list_widget or self.list_widget.isAncestorOf(watched)
                self._skip_auto_predict = True
                if from_list:
                    self._commit_list_edit()
                    self._keep_list_focus = True
                if event.isAutoRepeat():
                    return True
                self._select_image_by_delta(-1 if event.key() == Qt.Key.Key_Up else 1)
            finally:
                self._keep_list_focus = False
                self._skip_auto_predict = False
                self._arrow_nav = False
            return True
        return super().eventFilter(watched, event)

    def _commit_list_edit(self) -> None:
        if self.list_widget.state() != QAbstractItemView.State.EditingState:
            return
        editor = QApplication.focusWidget()
        if editor is None or not self.list_widget.isAncestorOf(editor):
            return
        self.list_widget.commitData(editor)
        self.list_widget.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)

    def _select_image_by_delta(self, delta: int) -> None:
        count = self.list_widget.rowCount()
        if count <= 0:
            return
        row = self.list_widget.currentRow()
        col = self.list_widget.currentColumn()
        if row < 0:
            next_row = 0 if delta > 0 else count - 1
        else:
            next_row = row + delta
        if next_row < 0 or next_row >= count:
            return
        if col < 0:
            col = 0
        self.list_widget.setCurrentCell(next_row, col)

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
        if self._predict_worker is not None and self._predict_worker.isRunning():
            self._predict_worker.wait(8000)
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
