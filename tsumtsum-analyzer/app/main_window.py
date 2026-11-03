from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QEvent, QSettings, QStandardPaths, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QFont, QImage, QPixmap, QResizeEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QHeaderView,
    QPushButton,
    QDialog,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.paths import APP_NAME, APP_ROOT, DATA_DIR, EXE_PATH, VIDEO_EXTENSIONS
from app.coin_model_sync import CoinModelCheckWorker, CoinModelSyncWorker
from tsumtsum_analyze.extractor import (
    VideoInfo,
    format_timecode,
    grab_frame,
    read_video_info,
)

STYLESHEET = """
QMainWindow, QWidget { background: #f4f6fb; }
QFrame#cell {
    background: #ffffff;
    border: 1px solid #1c2430;
}
QPushButton {
    background: #ffffff;
    color: #1c2430;
    border: 1px solid #d0d7e2;
    border-radius: 10px;
    padding: 12px 18px;
    font-weight: 700;
}
QPushButton[modeActive="true"] {
    background: #d7e4ff;
    border: 1px solid #6f8fdb;
    color: #1c2430;
}
QPushButton[modeActive="true"]:disabled {
    background: #d7e4ff;
    border: 1px solid #6f8fdb;
    color: #1c2430;
}
QLabel#cell_num {
    color: #1c2430;
    font-size: 28px;
    font-weight: 700;
}
QLabel#hint {
    color: #5a6577;
}
QLabel#preview {
    background: #10141c;
    color: #9aa7b8;
}
QFrame#lamp {
    background: #eef1f6;
    border: 1px solid #c5ced9;
    border-radius: 8px;
}
QFrame#lamp[armed="false"] {
    background: #d8dce3;
    border: 1px solid #aeb6c2;
}
QLabel#lamp_dot {
    background: #9aa7b8;
    border: 1px solid #7f8b9a;
    border-radius: 20px;
}
QLabel#lamp_dot[lit="true"] {
    background: #3dde7a;
    border: 1px solid #1faa52;
}
QFrame#lamp[armed="false"] QLabel#lamp_dot {
    background: #c5ccd6;
    border: 1px solid #a7b0bd;
}
QLabel#lamp_text {
    color: #1c2430;
    font-weight: 700;
}
QFrame#lamp[armed="false"] QLabel#lamp_text {
    color: #8a93a3;
}
QLabel#lamp_value {
    color: #1c2430;
    font-weight: 700;
}
QFrame#calc_result {
    background: #ffffff;
    border: 1px solid #1c2430;
}
QLabel#calc_result_text {
    color: #1c2430;
    background: transparent;
    border: none;
}
QWidget#play_host {
    background: #ffffff;
}
QTableWidget#play_table {
    background: #ffffff;
    color: #1c2430;
    border: none;
    border-right: 1px solid #1c2430;
    gridline-color: transparent;
    font-size: 7pt;
}
QTableWidget#play_table::item {
    padding: 0 0.5em;
    border: none;
    border-left: 1px solid #1c2430;
    border-bottom: 1px solid #1c2430;
    color: #1c2430;
}
QTableWidget#play_table::item:selected {
    background: #ffffff;
    color: #1c2430;
}
QTableWidget#play_table QLineEdit {
    color: #1c2430;
    background: #ffffff;
    selection-color: #1c2430;
    selection-background-color: #d7e4ff;
}
QTableWidget#play_table QHeaderView::section {
    background: #ffffff;
    color: #1c2430;
    border: none;
    border-left: 1px solid #1c2430;
    border-top: 1px solid #1c2430;
    border-bottom: 1px solid #1c2430;
    padding: 0 0.5em;
    font-weight: 700;
    font-size: 7pt;
}
"""

START_SCREEN_LAMP = "スタート画面"
START_SCREEN_SCENE_KEY = "item"
READY_LAMP = "READY"
READY_SCENE_KEY = "raredy"
GO_LAMP = "GO"
GO_SCENE_KEY = "go"
TIMEUP_LAMP = "TIME UP"
TIMEUP_SCENE_KEY = "timeup"
COIN_LAMP = "COIN"
COIN_SCENE_KEY = "coin"
RESULT_LAMP = "RESULT"
RESULT_SCENE_KEY = "result"
FEVER_LAMP = "FEVER"
FEVER_SCENE_KEY = "fever"
SKILL_LAMP = "SKILL"
MY_TSUM_LAMP = "マイツム"
USED_ITEM_LAMP = "アイテム"
SCENE_LAMP_KEYS = (
    (START_SCREEN_SCENE_KEY, START_SCREEN_LAMP),
    (READY_SCENE_KEY, READY_LAMP),
    (GO_SCENE_KEY, GO_LAMP),
    (TIMEUP_SCENE_KEY, TIMEUP_LAMP),
)
COIN_READ_KEYS = (
    (COIN_SCENE_KEY, COIN_LAMP, "coin"),
    (RESULT_SCENE_KEY, RESULT_LAMP, "result_coin"),
)


def format_go_timeup(elapsed_sec: float) -> str:
    total = int(float(elapsed_sec) + 0.5)
    if total < 0:
        total = 0
    minutes, seconds = divmod(total, 60)
    return f"GO > TIME UP : {minutes:02d} 分 {seconds:02d}秒"


class ExeBuildWorker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            python = Path(sys.executable)
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            check = subprocess.run(
                [str(python), "-m", "PyInstaller", "--version"],
                check=False,
                capture_output=True,
                text=True,
                creationflags=flags,
            )
            if check.returncode != 0:
                install = subprocess.run(
                    [str(python), "-m", "pip", "install", "pyinstaller"],
                    check=False,
                    capture_output=True,
                    text=True,
                    creationflags=flags,
                )
                if install.returncode != 0:
                    err = (install.stderr or install.stdout or "PyInstaller を入れられませんでした").strip()
                    self.failed.emit(err)
                    return
            spec = APP_ROOT / "tsumtsum-analyzer.spec"
            if not spec.is_file():
                self.failed.emit(f"spec がありません。\n{spec}")
                return
            result = subprocess.run(
                [
                    str(python),
                    "-m",
                    "PyInstaller",
                    "--noconfirm",
                    "--clean",
                    str(spec),
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=str(APP_ROOT),
                creationflags=flags,
            )
            if result.returncode != 0 or not EXE_PATH.is_file():
                err = (result.stderr or result.stdout or ".exe を作れませんでした").strip()
                self.failed.emit(err[-4000:])
                return
            self.finished_ok.emit(EXE_PATH)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ツムツム解析")
        self.setWindowState(Qt.WindowState.WindowMaximized)
        self.setStyleSheet(STYLESHEET)
        self._settings = QSettings("workshop", "TsumTsumAnalyzer")
        self._video_path: Path | None = None
        self.info: VideoInfo | None = None
        self._cap = None
        self._cap_next = 0
        self._play_frame = 0
        self._play_syncing = False
        self._play_rate = 1.0
        self._audio_ok = False
        self._audio_clock = True
        self._analyzing = False
        self._scene_model = None
        self._scene_classes: tuple[str, ...] = ()
        self._scene_device = None
        self._scene_transform = None
        self._tsum_reader = None
        self._item_store = None
        self._lamp_lit: dict[str, bool] = {}
        self._lamp_armed: dict[str, bool] = {}
        self._fever_count = 0
        self._fever_active = False
        self._skill_count = 0
        self._skill_raw = 0
        self._skill_off = 0
        self._skill_episode = False
        self._skill_last_frame: int | None = None
        self._skill_prototypes: list | None = None
        self._skill_limit = 0.0
        self._analyze_next_frame = 0
        self._go_frame: int | None = None
        self._timeup_frame: int | None = None
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._player_tick)
        self._audio_out = QAudioOutput(self)
        self._audio_player = QMediaPlayer(self)
        self._audio_player.setAudioOutput(self._audio_out)
        self._audio_player.errorOccurred.connect(self._on_audio_error)
        self._audio_player.mediaStatusChanged.connect(self._on_audio_status)
        self._play_fitting = False
        self._play_refreshing = False
        self._play_base_font = QFont()
        self._play_host: QWidget | None = None
        self._cell2: QFrame | None = None
        self._cell6: QFrame | None = None
        self._display_frame: QFrame | None = None
        self._display_frame_box: QVBoxLayout | None = None
        self._build_ui()
        self._apply_cell2_size()
        self._apply_cell6_lamp_size()
        self._set_player_enabled(False)
        self._apply_volume(int(self._settings.value("volume", 80) or 80))
        self._coin_sync: CoinModelSyncWorker | None = None
        self._coin_check: CoinModelCheckWorker | None = None
        self._start_coin_model_check()

    def _start_coin_model_check(self) -> None:
        worker = CoinModelCheckWorker(self)
        worker.checked.connect(self._on_coin_models_checked)
        self._coin_check = worker
        worker.start()

    def _on_coin_models_checked(self, differs: bool) -> None:
        button = getattr(self, "_coin_update_button", None)
        if button is None:
            return
        button.setText("更新あり" if differs else "更新なし")
        button.setEnabled(bool(differs))

    def _update_coin_models(self) -> None:
        running = self._coin_sync
        if running is not None and running.isRunning():
            return
        button = self._coin_update_button
        button.setEnabled(False)
        worker = CoinModelSyncWorker(self)
        worker.updated.connect(self._on_coin_models_updated)
        worker.failed.connect(self._on_coin_models_failed)
        self._coin_sync = worker
        worker.start()

    def _on_coin_models_updated(self, names: list) -> None:
        if names:
            from app.play_coin import reset_play_predictor

            reset_play_predictor()
        self._on_coin_models_checked(False)

    def _on_coin_models_failed(self) -> None:
        self._on_coin_models_checked(True)

    def _screen_size(self) -> tuple[int, int]:
        screen = self.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return 1920, 1080
        geo = screen.availableGeometry()
        return int(geo.width()), int(geo.height())

    def _apply_cell2_size(self) -> None:
        cell = self._cell2
        if cell is None:
            return
        _sw, sh = self._screen_size()
        height = max(1, int(sh * 0.8))
        width = max(1, int(height * 3 / 4))
        cell.setFixedSize(width, height)
        if self._display_frame_box is not None:
            margin_y = max(0, int(height * 0.02))
            self._display_frame_box.setContentsMargins(5, margin_y, 5, margin_y)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_cell2_size()
        self._apply_cell6_lamp_size()
        QTimer.singleShot(0, self._fit_play_columns)

    def eventFilter(self, watched, event) -> bool:
        if watched is getattr(self, "_play_window", None) and event.type() == QEvent.Type.Resize:
            self._fit_play_columns()
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            if watched in {self.preview, self._display_frame} and self.info is not None:
                self._player_toggle()
                return True
            name = watched.property("lamp_name") if isinstance(watched, QFrame) else None
            if isinstance(name, str) and name in self._cell6_lamps_by_name:
                self._toggle_lamp_armed(name)
                return True
        return super().eventFilter(watched, event)

    def _calc_result_height(self) -> int:
        frame = getattr(self, "_calc_result_frame", None)
        label = getattr(self, "_calc_result_value", None)
        box = getattr(self, "_calc_result_box", None)
        if frame is None or label is None or box is None:
            return 0
        line = max(1, label.fontMetrics().lineSpacing())
        margins = box.contentsMargins()
        return line * 3 + margins.top() + margins.bottom() + frame.frameWidth() * 2

    def _apply_cell6_lamp_size(self) -> None:
        cell = getattr(self, "_cell6", None)
        lamps = getattr(self, "_cell6_lamps", None)
        rows = getattr(self, "_cell6_lamp_rows", None)
        box = getattr(self, "_cell6_box", None)
        if cell is None or not lamps or not rows or box is None:
            return
        margins = box.contentsMargins()
        spacing = box.spacing()
        count = len(lamps)
        result = getattr(self, "_calc_result_frame", None)
        result_h = 0
        extra = 0
        if result is not None:
            result_h = self._calc_result_height()
            result.setFixedHeight(result_h)
            extra = 1
        avail_h = (
            cell.height()
            - margins.top()
            - margins.bottom()
            - spacing * max(0, count - 1 + extra)
            - result_h
        )
        height = max(1, avail_h // count)
        width = max(1, int(cell.width() / 3))
        for row, lamp in zip(rows, lamps):
            row.setFixedHeight(height)
            lamp.setFixedSize(width, height)
            dot = lamp.property("lamp_dot")
            if isinstance(dot, QLabel):
                side = max(8, min(height - 8, width // 5))
                dot.setFixedSize(side, side)

    def _build_ui(self) -> None:
        root = QWidget()
        grid = QGridLayout(root)
        grid.setContentsMargins(24, 24, 24, 24)
        grid.setSpacing(0)

        def make_cell() -> QFrame:
            cell = QFrame()
            cell.setObjectName("cell")
            cell.setFrameShape(QFrame.Shape.Box)
            cell.setFrameShadow(QFrame.Shadow.Plain)
            cell.setLineWidth(1)
            cell.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            return cell

        def put_num(cell: QFrame, text: str) -> None:
            box = QVBoxLayout(cell)
            box.setContentsMargins(12, 12, 12, 12)
            num = QLabel(text)
            num.setObjectName("cell_num")
            num.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            box.addWidget(num)
            box.addStretch(1)

        top = make_cell()
        grid.addWidget(top, 0, 0, 1, 3)
        put_num(top, "0")

        c1 = make_cell()
        grid.addWidget(c1, 1, 0, 2, 1)
        c1_box = QVBoxLayout(c1)
        c1_box.setContentsMargins(12, 12, 12, 12)
        c1_box.setSpacing(0)
        play_button = QPushButton("DATA")
        play_button.clicked.connect(self._show_play_table)
        c1_box.addWidget(
            play_button, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        c1_box.addStretch(1)
        self._play_button = play_button
        play_table = QTableWidget(0, 14)
        play_table.setObjectName("play_table")
        play_table.setFrameShape(QFrame.Shape.NoFrame)
        play_table.setShowGrid(False)
        play_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.SelectedClicked
            | QTableWidget.EditTrigger.EditKeyPressed
            | QTableWidget.EditTrigger.AnyKeyPressed
        )
        play_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        play_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        play_table.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        play_table.itemChanged.connect(self._on_play_item_changed)
        play_table.verticalHeader().setVisible(False)
        play_table.setHorizontalHeaderLabels(
            [
                "動画のファイル名",
                "使用ツム",
                "アイテム",
                "プレイ時間",
                "素コイン",
                "コイン",
                "倍率",
                "コイン利益",
                "素コイン合計",
                "コイン合計",
                "利益合計",
                "効率（素）",
                "効率（仮想）",
                "効率（現実）",
            ]
        )
        play_table.horizontalHeader().setHighlightSections(False)
        play_table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        for col in range(play_table.columnCount()):
            header_item = play_table.horizontalHeaderItem(col)
            if header_item is not None:
                header_item.setTextAlignment(
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
                )
        play_table.horizontalHeader().setStretchLastSection(False)
        play_table.horizontalHeader().setMinimumSectionSize(1)
        play_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        play_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        play_table.setWordWrap(False)
        play_table.setMinimumWidth(0)
        play_table.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        play_host = QWidget()
        play_host.setObjectName("play_host")
        play_box = QVBoxLayout(play_host)
        play_box.setContentsMargins(0, 0, 0, 0)
        play_box.setSpacing(0)
        play_line = QHBoxLayout()
        play_line.setContentsMargins(0, 0, 0, 0)
        play_line.setSpacing(0)
        play_line.addStretch(1)
        play_line.addWidget(play_table, 0, Qt.AlignmentFlag.AlignTop)
        play_line.addStretch(1)
        play_box.addLayout(play_line)
        play_box.addStretch(1)
        play_window = QDialog(self)
        play_window.setWindowTitle("DATA")
        play_window.setModal(False)
        play_window_box = QVBoxLayout(play_window)
        play_window_box.setContentsMargins(0, 0, 0, 0)
        play_window_box.setSpacing(0)
        play_window_box.addWidget(play_host)
        play_window.installEventFilter(self)
        self._play_window = play_window
        self._play_host = play_host
        self._play_table = play_table
        self._play_base_font = QFont(play_table.font())
        self._play_base_font.setPointSize(7)
        c2 = make_cell()
        c2.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        grid.addWidget(c2, 1, 1, 2, 1)
        c2_box = QVBoxLayout(c2)
        c2_box.setSpacing(0)
        c2_box.setContentsMargins(0, 0, 0, 0)
        display_host = QWidget()
        display_box = QVBoxLayout(display_host)
        display_box.setSpacing(0)
        display_box.setContentsMargins(0, 0, 0, 0)
        display_frame = make_cell()
        display_frame.setObjectName("display_frame")
        display_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        display_inner = QVBoxLayout(display_frame)
        display_inner.setContentsMargins(0, 0, 0, 0)
        display_inner.setSpacing(0)
        self.preview = QLabel("")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.preview.setCursor(Qt.CursorShape.PointingHandCursor)
        display_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        display_inner.addWidget(self.preview, 1)
        display_box.addWidget(display_frame, 1)
        c2_box.addWidget(display_host, 1)
        self._cell2 = c2
        self._display_frame = display_frame
        self._display_frame_box = display_box
        self.preview.installEventFilter(self)
        display_frame.installEventFilter(self)

        c3 = make_cell()
        grid.addWidget(c3, 1, 2)
        c3_box = QVBoxLayout(c3)
        c3_box.setContentsMargins(12, 12, 12, 12)
        c3_box.setSpacing(8)
        open_btn = QPushButton("開く")
        open_btn.clicked.connect(self.open_video)
        c3_box.addWidget(
            open_btn, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        c3_box.addStretch(1)
        self._open_btn = open_btn

        self.player_time = QLabel("—")
        self.player_time.setObjectName("hint")
        self.player_time.setWordWrap(True)
        c3_box.addWidget(self.player_time)
        self.player_slider = QSlider(Qt.Orientation.Horizontal)
        self.player_slider.setEnabled(False)
        self.player_slider.valueChanged.connect(self._player_on_slider)
        c3_box.addWidget(self.player_slider)
        play_row = QHBoxLayout()
        play_row.setSpacing(6)
        self.player_rate_quarter_btn = QPushButton("1/4")
        self.player_rate_half_btn = QPushButton("1/2")
        self.player_play_btn = QPushButton("再生")
        self.player_analyze_btn = QPushButton("解析")
        self.player_rate_double_btn = QPushButton("×2")
        self.player_rate_quad_btn = QPushButton("×4")
        self.player_rate_quarter_btn.clicked.connect(lambda: self._set_play_rate(0.25))
        self.player_rate_half_btn.clicked.connect(lambda: self._set_play_rate(0.5))
        self.player_play_btn.clicked.connect(self._player_toggle)
        self.player_analyze_btn.clicked.connect(self.start_analyze)
        self.player_rate_double_btn.clicked.connect(lambda: self._set_play_rate(2.0))
        self.player_rate_quad_btn.clicked.connect(lambda: self._set_play_rate(4.0))
        play_row.addWidget(self.player_rate_quarter_btn, 1)
        play_row.addWidget(self.player_rate_half_btn, 1)
        play_row.addWidget(self.player_play_btn, 1)
        play_row.addWidget(self.player_analyze_btn, 1)
        play_row.addWidget(self.player_rate_double_btn, 1)
        play_row.addWidget(self.player_rate_quad_btn, 1)
        c3_box.addLayout(play_row)
        self._rate_buttons = {
            0.25: self.player_rate_quarter_btn,
            0.5: self.player_rate_half_btn,
            2.0: self.player_rate_double_btn,
            4.0: self.player_rate_quad_btn,
        }
        step_row = QHBoxLayout()
        step_row.setSpacing(6)
        self._step_buttons: list[QPushButton] = []
        for delta, label in (
            (-10, "-10"),
            (-5, "-5"),
            (-1, "-1"),
            (1, "+1"),
            (5, "+5"),
            (10, "+10"),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, value=delta: self._player_step(value)
            )
            step_row.addWidget(button, 1)
            self._step_buttons.append(button)
        c3_box.addLayout(step_row)
        volume_row = QHBoxLayout()
        volume_row.setSpacing(8)
        volume_label = QLabel("音量")
        volume_label.setObjectName("hint")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setEnabled(False)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.volume_value = QLabel("80")
        self.volume_value.setObjectName("hint")
        self.volume_value.setMinimumWidth(28)
        volume_row.addWidget(volume_label)
        volume_row.addWidget(self.volume_slider, 1)
        volume_row.addWidget(self.volume_value)
        c3_box.addLayout(volume_row)

        c6 = make_cell()
        grid.addWidget(c6, 2, 2)
        c6_box = QVBoxLayout(c6)
        c6_box.setContentsMargins(12, 12, 12, 12)
        c6_box.setSpacing(4)
        self._cell6 = c6
        self._cell6_box = c6_box
        self._cell6_lamps: list[QFrame] = []
        self._cell6_lamp_rows: list[QWidget] = []
        self._cell6_lamps_by_name: dict[str, QFrame] = {}
        self._cell6_values_by_name: dict[str, QLabel] = {}
        for label in (
            "スタート画面",
            "マイツム",
            "アイテム",
            "READY",
            "GO",
            "FEVER",
            "SKILL",
            "TIME UP",
            "COIN",
            "RESULT",
        ):
            host = QWidget()
            host_row = QHBoxLayout(host)
            host_row.setContentsMargins(0, 0, 0, 0)
            host_row.setSpacing(8)
            lamp = QFrame()
            lamp.setObjectName("lamp")
            lamp.setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
            )
            lamp.setCursor(Qt.CursorShape.PointingHandCursor)
            lamp.setProperty("lamp_name", label)
            lamp.setProperty("armed", "true")
            lamp.installEventFilter(self)
            row = QHBoxLayout(lamp)
            row.setContentsMargins(8, 2, 8, 2)
            row.setSpacing(8)
            dot = QLabel()
            dot.setObjectName("lamp_dot")
            dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            text = QLabel(label)
            text.setObjectName("lamp_text")
            text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            row.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(text, 1, Qt.AlignmentFlag.AlignVCenter)
            lamp.setProperty("lamp_dot", dot)
            value = QLabel("")
            value.setObjectName("lamp_value")
            value.setWordWrap(True)
            host_row.addWidget(lamp, 0, Qt.AlignmentFlag.AlignLeft)
            host_row.addWidget(value, 1, Qt.AlignmentFlag.AlignVCenter)
            c6_box.addWidget(host)
            self._cell6_lamp_rows.append(host)
            self._cell6_lamps.append(lamp)
            self._cell6_lamps_by_name[label] = lamp
            self._cell6_values_by_name[label] = value
            self._lamp_armed[label] = True
        calc = QFrame()
        calc.setObjectName("calc_result")
        calc.setFrameShape(QFrame.Shape.Box)
        calc.setFrameShadow(QFrame.Shadow.Plain)
        calc.setLineWidth(1)
        calc.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        calc_box = QVBoxLayout(calc)
        calc_box.setContentsMargins(8, 2, 8, 2)
        calc_box.setSpacing(0)
        calc_value = QLabel("")
        calc_value.setObjectName("calc_result_text")
        calc_value.setWordWrap(True)
        calc_value.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        calc_box.addWidget(calc_value)
        c6_box.addWidget(calc)
        self._calc_result_frame = calc
        self._calc_result_box = calc_box
        self._calc_result_value = calc_value
        self._apply_cell6_lamp_size()
        c7 = make_cell()
        grid.addWidget(c7, 3, 0)
        put_num(c7, "7")
        c8 = make_cell()
        grid.addWidget(c8, 3, 1)
        c8_box = QVBoxLayout(c8)
        c8_box.setContentsMargins(12, 12, 12, 12)
        coin_update_button = QPushButton("")
        coin_update_button.setEnabled(False)
        coin_update_button.clicked.connect(self._update_coin_models)
        c8_box.addStretch(1)
        c8_box.addWidget(coin_update_button)
        c8_box.addStretch(1)
        self._coin_update_button = coin_update_button
        bottom_right = make_cell()
        grid.addWidget(bottom_right, 3, 2)
        br = QVBoxLayout(bottom_right)
        br.setContentsMargins(12, 12, 12, 12)
        launch_row = QHBoxLayout()
        launch_row.setSpacing(8)
        exe_btn = QPushButton(".exe 化")
        exe_btn.clicked.connect(self.build_exe)
        shortcut_btn = QPushButton("起動アイコンをデスクトップに作成")
        shortcut_btn.clicked.connect(self.create_launch_shortcut)
        launch_row.addWidget(exe_btn, 1)
        launch_row.addWidget(shortcut_btn, 1)
        self._exe_btn = exe_btn
        self._shortcut_btn = shortcut_btn
        self._exe_worker: ExeBuildWorker | None = None
        br.addStretch(1)
        br.addLayout(launch_row)
        br.addStretch(1)

        for row in range(4):
            grid.setRowStretch(row, 1)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        self.setCentralWidget(root)
        self._refresh_play_list()

    def _show_play_table(self) -> None:
        window = self._play_window
        screen = window.screen() or self.screen() or QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen is not None else None
        if geo is not None:
            window.setGeometry(
                int(geo.x()),
                int(geo.y()),
                max(1, int(geo.width() * 2 // 3)),
                int(geo.height()),
            )
        window.show()
        window.raise_()
        self._fit_play_columns()

    def _plays_path(self) -> Path:
        return DATA_DIR / "plays.json"

    def _load_plays(self) -> list[dict]:
        path = self._plays_path()
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    def _write_plays(self, plays: list[dict]) -> None:
        path = self._plays_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(plays, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _play_cell_align(self, col: int):
        if col == 6:
            return Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        if col in {3, 4, 5, 7, 8, 9, 10, 11, 12, 13}:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

    def _play_duration_parts(self, text: str) -> tuple[int, int] | None:
        raw = str(text or "")
        if "分" not in raw or "秒" not in raw:
            return None
        left, right = raw.split("分", 1)
        minutes = self._play_int(left)
        seconds = self._play_int(right.split("秒", 1)[0])
        if minutes is None or seconds is None:
            return None
        return minutes, seconds

    def _play_per_min_text(self, amount: int | None, duration_sec: int | None) -> str:
        if amount is None or not duration_sec:
            return ""
        return f"{(amount / duration_sec) * 60.0:.2f}"

    def _play_int(self, text: str) -> int | None:
        digits = "".join(char for char in str(text or "") if char.isdigit())
        if not digits:
            return None
        return int(digits)

    def _play_items_text(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw or raw == "なし":
            return ""
        return " ".join(part for part in raw.replace("、", " ").split() if part)

    def _play_item_cost(self, text: str) -> int:
        from tsumtsum_analyze.item_slots import ITEM_COIN_COST, ITEM_RESULT_NAMES

        by_name = {
            name: int(ITEM_COIN_COST.get(slot, 0))
            for slot, name in ITEM_RESULT_NAMES.items()
        }
        by_name["5＞4"] = by_name.get("5>4", 0)
        total = 0
        for part in self._play_items_text(text).split():
            total += by_name.get(part, 0)
        return total

    def _play_profit(self, record: dict) -> int | None:
        result_n = self._play_int(str(record.get("result") or ""))
        if result_n is None:
            return None
        return result_n - self._play_item_cost(str(record.get("item") or ""))

    def _play_row_cells(
        self, record: dict, coin_sum: int, result_sum: int, profit_sum: int
    ) -> list[str]:
        coin_n = self._play_int(str(record.get("coin") or ""))
        result_n = self._play_int(str(record.get("result") or ""))
        profit_n = self._play_profit(record)
        coin_text = f"{coin_n:,}" if coin_n is not None else ""
        result_text = f"{result_n:,}" if result_n is not None else ""
        profit_text = f"{profit_n:,}" if profit_n is not None else ""
        if coin_n is not None and result_n is not None and coin_n > 0:
            rate = f"×{result_n / coin_n:.1f}"
        else:
            rate = ""
        parts = self._play_duration_parts(str(record.get("go_timeup") or ""))
        if parts is None:
            duration_sec = None
            play_time = ""
        else:
            minutes, seconds = parts
            duration_sec = minutes * 60 + seconds
            play_time = f"{minutes:02d} 分 {seconds:02d}秒"
        return [
            str(record.get("video") or "").strip(),
            str(record.get("tsum") or "").strip(),
            self._play_items_text(str(record.get("item") or "")),
            play_time,
            coin_text,
            result_text,
            rate,
            profit_text,
            f"{coin_sum:,}",
            f"{result_sum:,}",
            f"{profit_sum:,}",
            self._play_per_min_text(coin_n, duration_sec),
            self._play_per_min_text(result_n, duration_sec),
            self._play_per_min_text(profit_n, duration_sec),
        ]

    def _refresh_play_list(self) -> None:
        table = getattr(self, "_play_table", None)
        if table is None:
            return
        self._play_refreshing = True
        try:
            self._fill_play_list(table)
        finally:
            self._play_refreshing = False

    def _fill_play_list(self, table: QTableWidget) -> None:
        plays = list(reversed(self._load_plays()))
        table.setRowCount(len(plays))
        coin_sum = 0
        result_sum = 0
        profit_sum = 0
        for row, record in enumerate(plays):
            coin_n = self._play_int(str(record.get("coin") or ""))
            result_n = self._play_int(str(record.get("result") or ""))
            profit_n = self._play_profit(record)
            if coin_n is not None:
                coin_sum += coin_n
            if result_n is not None:
                result_sum += result_n
            if profit_n is not None:
                profit_sum += profit_n
            for col, text in enumerate(
                self._play_row_cells(record, coin_sum, result_sum, profit_sum)
            ):
                cell = QTableWidgetItem(text)
                cell.setTextAlignment(self._play_cell_align(col))
                flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                if col in {1, 4, 5}:
                    flags |= Qt.ItemFlag.ItemIsEditable
                cell.setFlags(flags)
                table.setItem(row, col, cell)
        table.resizeRowsToContents()
        self._fit_play_columns()

    def _on_play_item_changed(self, item: QTableWidgetItem) -> None:
        if self._play_refreshing:
            return
        col = item.column()
        if col == 1:
            key = "tsum"
            value = item.text().strip()
        elif col == 4:
            key = "coin"
            number = self._play_int(item.text())
            value = f"{number:,}" if number is not None else ""
        elif col == 5:
            key = "result"
            number = self._play_int(item.text())
            value = f"{number:,}" if number is not None else ""
        else:
            return
        plays = self._load_plays()
        file_index = len(plays) - 1 - item.row()
        if file_index < 0 or file_index >= len(plays):
            return
        stored = str(plays[file_index].get(key) or "")
        if stored != value:
            plays[file_index][key] = value
            self._write_plays(plays)
        if stored != value or item.text() != value:
            self._refresh_play_list()

    def _play_columns_width(self, font: QFont) -> int:
        table = self._play_table
        header = table.horizontalHeader()
        table.setFont(font)
        header.setFont(font)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.resizeColumnsToContents()
        table.resizeRowsToContents()
        return sum(table.columnWidth(col) for col in range(table.columnCount()))

    def _play_content_height(self) -> int:
        table = self._play_table
        height = table.horizontalHeader().height() + table.frameWidth() * 2
        for row in range(table.rowCount()):
            height += table.rowHeight(row)
        return height

    def _place_play_table(self) -> None:
        table = self._play_table
        host = self._play_host
        if host is None or host.height() < 20:
            return
        width = sum(table.columnWidth(col) for col in range(table.columnCount()))
        width += table.frameWidth() * 2
        height = self._play_content_height()
        if host.height() > 20 and height > host.height():
            height = host.height()
            width += table.verticalScrollBar().sizeHint().width()
        table.setFixedSize(max(1, width), max(1, height))

    def _fit_play_columns(self) -> None:
        table = getattr(self, "_play_table", None)
        if table is None or self._play_fitting:
            return
        if not table.isVisible():
            return
        self._play_fitting = True
        try:
            header = table.horizontalHeader()
            self._play_columns_width(self._play_base_font)
            widths = [table.columnWidth(col) for col in range(table.columnCount())]
            header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            for col, width in enumerate(widths):
                header.resizeSection(col, width)
            self._place_play_table()
        finally:
            self._play_fitting = False

    def _lamp_text(self, name: str) -> str:
        value = self._cell6_values_by_name.get(name)
        if value is None:
            return ""
        return value.text().strip()

    def _current_play_record(self) -> dict | None:
        record = {
            "video": self._video_path.name if self._video_path is not None else "",
            "tsum": self._lamp_text(MY_TSUM_LAMP),
            "item": self._lamp_text(USED_ITEM_LAMP),
            "fever": self._lamp_text(FEVER_LAMP),
            "skill": self._lamp_text(SKILL_LAMP),
            "coin": self._lamp_text(COIN_LAMP),
            "result": self._lamp_text(RESULT_LAMP),
            "go_timeup": self._calc_result_value.text().strip(),
        }
        if not any(record[key] for key in record if key != "video"):
            return None
        return record

    def _save_current_play(self) -> None:
        record = self._current_play_record()
        if record is None:
            return
        plays = self._load_plays()
        video = record["video"]
        if video:
            plays = [item for item in plays if item.get("video") != video]
        plays.insert(0, record)
        self._write_plays(plays)
        self._refresh_play_list()

    def _set_player_enabled(self, enabled: bool) -> None:
        self.player_slider.setEnabled(enabled)
        self.player_play_btn.setEnabled(enabled)
        for button in self._step_buttons:
            button.setEnabled(enabled)
        for button in self._rate_buttons.values():
            button.setEnabled(enabled)
        self.volume_slider.setEnabled(enabled and self._has_audio_output())
        self._refresh_analyze_enabled()

    def _refresh_analyze_enabled(self) -> None:
        self.player_analyze_btn.setEnabled(
            self.info is not None and not self._play_timer.isActive()
        )
        self._refresh_mode_button_styles()

    def _set_mode_button_active(self, button: QPushButton, active: bool) -> None:
        button.setProperty("modeActive", "true" if active else "false")
        style = button.style()
        style.unpolish(button)
        style.polish(button)
        button.update()

    def _refresh_mode_button_styles(self) -> None:
        self._set_mode_button_active(self.player_play_btn, self._play_timer.isActive())
        self._set_mode_button_active(self.player_analyze_btn, self._analyzing)

    def _reset_lamps(self) -> None:
        self._lamp_lit = {}
        self._fever_count = 0
        self._fever_active = False
        self._skill_count = 0
        self._skill_raw = 0
        self._skill_off = 0
        self._skill_episode = False
        self._skill_last_frame = None
        self._skill_prototypes = None
        self._skill_limit = 0.0
        self._analyze_next_frame = 0
        self._go_frame = None
        self._timeup_frame = None
        self._set_calc_result("")
        for lamp in self._cell6_lamps:
            dot = lamp.property("lamp_dot")
            if isinstance(dot, QLabel):
                dot.setProperty("lit", "false")
                style = dot.style()
                style.unpolish(dot)
                style.polish(dot)
                dot.update()
        for value in self._cell6_values_by_name.values():
            value.setText("")

    def _is_lamp_armed(self, name: str) -> bool:
        return bool(self._lamp_armed.get(name, True))

    def _set_lamp_armed_style(self, name: str) -> None:
        lamp = self._cell6_lamps_by_name.get(name)
        if lamp is None:
            return
        lamp.setProperty("armed", "true" if self._is_lamp_armed(name) else "false")
        style = lamp.style()
        style.unpolish(lamp)
        style.polish(lamp)
        lamp.update()
        dot = lamp.property("lamp_dot")
        if isinstance(dot, QLabel):
            style = dot.style()
            style.unpolish(dot)
            style.polish(dot)
            dot.update()

    def _toggle_lamp_armed(self, name: str) -> None:
        armed = not self._is_lamp_armed(name)
        self._lamp_armed[name] = armed
        if not armed:
            self._set_lamp_on(name, False)
            self._set_lamp_value(name, "")
        self._set_lamp_armed_style(name)

    def _set_lamp_on(self, name: str, on: bool = True) -> None:
        lamp = self._cell6_lamps_by_name.get(name)
        if lamp is None:
            return
        if on and not self._is_lamp_armed(name):
            return
        self._lamp_lit[name] = bool(on)
        dot = lamp.property("lamp_dot")
        if not isinstance(dot, QLabel):
            return
        show_lit = bool(on) and self._is_lamp_armed(name)
        dot.setProperty("lit", "true" if show_lit else "false")
        style = dot.style()
        style.unpolish(dot)
        style.polish(dot)
        dot.update()

    def _set_lamp_value(self, name: str, text: str) -> None:
        value = self._cell6_values_by_name.get(name)
        if value is None:
            return
        value.setText(text)

    def _set_calc_result(self, text: str) -> None:
        label = getattr(self, "_calc_result_value", None)
        if label is None:
            return
        label.setText(text)

    def _note_go_timeup(self, lamp: str) -> None:
        if lamp == GO_LAMP and self._go_frame is None:
            self._go_frame = self._play_frame
        elif (
            lamp == TIMEUP_LAMP
            and self._timeup_frame is None
            and self._go_frame is not None
            and self._play_frame > self._go_frame
        ):
            self._timeup_frame = self._play_frame
        self._update_go_timeup_text()

    def _update_go_timeup_text(self) -> None:
        if self._go_frame is None or self._timeup_frame is None or self.info is None:
            return
        if self.info.fps <= 0 or self._timeup_frame <= self._go_frame:
            return
        elapsed = (self._timeup_frame - self._go_frame) / self.info.fps
        self._set_calc_result(format_go_timeup(elapsed))

    def _ensure_scene_model(self) -> bool:
        if self._scene_model is not None:
            return True
        from tsumtsum_analyze.scene_labels import scene_model_ready
        from tsumtsum_analyze.scene_scan import (
            IMAGENET_MEAN,
            IMAGENET_STD,
            SCENE_INPUT,
            load_scene_checkpoint,
        )
        from torchvision import transforms
        import torch

        if not scene_model_ready():
            return False
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model, classes = load_scene_checkpoint(device)
        self._scene_model = model
        self._scene_classes = classes
        self._scene_device = device
        self._scene_transform = transforms.Compose(
            [
                transforms.Resize((SCENE_INPUT, SCENE_INPUT)),
                transforms.ToTensor(),
                transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
            ]
        )
        return True

    def _analyze_sample_step(self) -> int:
        if self.info is None:
            return 1
        return max(1, int(round(self.info.fps * 0.1)))

    def _analyze_frame(self, image) -> None:
        if not self._analyzing:
            return
        if self._play_frame < self._analyze_next_frame:
            return
        self._analyze_next_frame = self._play_frame + self._analyze_sample_step()
        if not self._ensure_scene_model():
            return
        from PIL import Image
        import torch
        from tsumtsum_analyze.item_slots import (
            ITEM_RESULT_NAMES,
            ITEM_SLOT_KEYS,
            ItemSlotStore,
            box_means_used,
        )
        from tsumtsum_analyze.item_teach import TsumReader, shown_tsum_name
        from tsumtsum_analyze.scene_scan import (
            KIND_THRESHOLD,
            SCENE_INPUT,
            _class_score,
        )

        small = cv2.resize(
            image, (SCENE_INPUT, SCENE_INPUT), interpolation=cv2.INTER_AREA
        )
        scene_rgb = Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
        tensor = self._scene_transform(scene_rgb).unsqueeze(0).to(self._scene_device)
        with torch.inference_mode():
            probs = torch.softmax(self._scene_model(tensor), dim=1)[0]
        fever_now = (
            _class_score(probs, self._scene_classes, FEVER_SCENE_KEY) >= KIND_THRESHOLD
        )
        if (
            fever_now
            and not self._fever_active
            and self._is_lamp_armed(FEVER_LAMP)
        ):
            self._fever_count += 1
            self._set_lamp_on(FEVER_LAMP, True)
            self._set_lamp_value(FEVER_LAMP, f"{self._fever_count}回")
            QTimer.singleShot(250, lambda: self._set_lamp_on(FEVER_LAMP, False))
        self._fever_active = fever_now
        need_my = self._is_lamp_armed(MY_TSUM_LAMP) and not self._lamp_lit.get(
            MY_TSUM_LAMP
        )
        need_item = self._is_lamp_armed(USED_ITEM_LAMP) and not self._lamp_lit.get(
            USED_ITEM_LAMP
        )
        on_start = (
            _class_score(probs, self._scene_classes, START_SCREEN_SCENE_KEY)
            >= KIND_THRESHOLD
        )
        for key, lamp in SCENE_LAMP_KEYS:
            if not self._is_lamp_armed(lamp):
                continue
            waiting_time = (
                lamp == GO_LAMP and self._go_frame is None
            ) or (
                lamp == TIMEUP_LAMP and self._timeup_frame is None
            )
            if self._lamp_lit.get(lamp) and not waiting_time:
                continue
            score = _class_score(probs, self._scene_classes, key)
            if score < KIND_THRESHOLD:
                continue
            if not self._lamp_lit.get(lamp):
                self._set_lamp_on(lamp, True)
            self._note_go_timeup(lamp)
        full_rgb = None
        if self._skill_prototypes is not None and self._is_lamp_armed(SKILL_LAMP):
            full_rgb = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            self._analyze_skill_frame(full_rgb)
        for scene_key, lamp, read_key in COIN_READ_KEYS:
            if not self._is_lamp_armed(lamp):
                continue
            score = _class_score(probs, self._scene_classes, scene_key)
            if score < KIND_THRESHOLD:
                continue
            number = self._read_coin_number(image, read_key)
            if not number:
                continue
            self._set_lamp_on(lamp, True)
            self._set_lamp_value(lamp, number)
        if not on_start:
            return
        if not need_my and not need_item:
            return
        if full_rgb is None:
            full_rgb = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        if need_my:
            if self._tsum_reader is None:
                self._tsum_reader = TsumReader()
            name = self._tsum_reader.read_screen(full_rgb)
            if name:
                self._set_lamp_on(MY_TSUM_LAMP, True)
                self._set_lamp_value(MY_TSUM_LAMP, shown_tsum_name(name))
                self._prepare_skill_detector(name)
        if need_item:
            if self._item_store is None:
                self._item_store = ItemSlotStore()
            width, height = full_rgb.size
            used: list[str] = []
            checked = False
            for slot in ITEM_SLOT_KEYS:
                box = self._item_store.box_for(slot, width, height)
                if box is None:
                    continue
                checked = True
                if box_means_used(full_rgb, box):
                    used.append(ITEM_RESULT_NAMES.get(slot, slot))
            if checked:
                self._set_lamp_on(USED_ITEM_LAMP, True)
                self._set_lamp_value(
                    USED_ITEM_LAMP, "、".join(used) if used else "なし"
                )

    def _read_coin_number(self, image, read_key: str) -> str:
        from PIL import Image
        from app.play_coin import read_play_coin

        rgb = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        try:
            return read_play_coin(rgb, read_key)
        except Exception:
            return ""

    def _prepare_skill_detector(self, tsum_name: str) -> None:
        from tsumtsum_analyze.item_teach import tsum_id_for_name
        from tsumtsum_analyze.skill_read import _match_limit, _prototypes_for

        tsum_id = tsum_id_for_name(tsum_name) or ""
        if not tsum_id:
            self._skill_prototypes = None
            self._skill_limit = 0.0
            return
        prototypes = _prototypes_for(tsum_id)
        if not prototypes:
            self._skill_prototypes = None
            self._skill_limit = 0.0
            return
        self._skill_prototypes = prototypes
        self._skill_limit = _match_limit(prototypes)

    def _analyze_skill_frame(self, rgb) -> None:
        if not self._skill_prototypes or self.info is None:
            return
        if not self._is_lamp_armed(SKILL_LAMP):
            return
        from tsumtsum_analyze.skill_read import (
            SKILL_HIT_STREAK,
            SKILL_MIN_GAP_SEC,
            SKILL_OFF_STREAK,
            _hits_skill,
        )

        if _hits_skill(rgb, self._skill_prototypes, self._skill_limit):
            self._skill_raw = min(self._skill_raw + 1, 30)
            self._skill_off = 0
            if self._skill_raw < SKILL_HIT_STREAK or self._skill_episode:
                return
            self._skill_episode = True
            last = self._skill_last_frame
            gap_ok = last is None or (
                (self._play_frame - last) / max(self.info.fps, 1e-6) >= SKILL_MIN_GAP_SEC
            )
            if not gap_ok:
                return
            self._skill_count += 1
            self._skill_last_frame = self._play_frame
            self._set_lamp_on(SKILL_LAMP, True)
            self._set_lamp_value(SKILL_LAMP, f"{self._skill_count}回")
            QTimer.singleShot(250, lambda: self._set_lamp_on(SKILL_LAMP, False))
            return
        self._skill_raw = 0
        self._skill_off += 1
        if self._skill_off >= SKILL_OFF_STREAK:
            self._skill_episode = False

    def start_analyze(self) -> None:
        if self.info is None or self._play_timer.isActive():
            return
        if not self._ensure_scene_model():
            QMessageBox.warning(
                self,
                "解析",
                "画面のモデルがありません。画像を教えて学習してください。",
            )
            return
        self._analyzing = True
        self._audio_clock = False
        self._analyze_next_frame = 0
        self._set_mode_button_active(self.player_analyze_btn, True)
        QApplication.processEvents()
        self._reset_lamps()
        self._show_frame(0)
        self._start_audio()
        self._play_timer.start()
        self.player_play_btn.setText("停止")
        self._refresh_analyze_enabled()

    def _has_audio_output(self) -> bool:
        try:
            return len(QMediaDevices.audioOutputs()) > 0
        except Exception:
            return False

    def _on_volume_changed(self, value: int) -> None:
        self._apply_volume(int(value))
        self._settings.setValue("volume", int(value))

    def _apply_volume(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(value)
        self.volume_slider.blockSignals(False)
        self.volume_value.setText(str(value))
        self._audio_out.setVolume(value / 100.0)
        self._audio_out.setMuted(value <= 0)

    def _ms_from_frame(self, frame: int) -> int:
        if self.info is None or self.info.fps <= 0:
            return 0
        return int(round(frame * 1000.0 / self.info.fps))

    def _frame_from_ms(self, ms: int) -> int:
        if self.info is None or self.info.fps <= 0:
            return 0
        return max(0, int(round(ms * self.info.fps / 1000.0)))

    def _on_audio_error(self, *_args) -> None:
        self._audio_ok = False

    def _on_audio_status(self, status) -> None:
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self._audio_ok = self._has_audio_output()
            self._apply_media_duration()
        elif status in (
            QMediaPlayer.MediaStatus.NoMedia,
            QMediaPlayer.MediaStatus.InvalidMedia,
        ):
            self._audio_ok = False

    def _apply_media_duration(self) -> None:
        if self.info is None:
            return
        ms = int(self._audio_player.duration())
        if ms <= 0 or self.info.fps <= 1e-3:
            return
        frames = max(1, int(round(ms * self.info.fps / 1000.0)))
        if frames <= self.info.frame_count:
            return
        self.info.frame_count = frames
        self.info.duration = ms / 1000.0
        self._player_sync_ui()

    def _last_frame(self) -> int:
        if self.info is None:
            return 0
        return max(self.info.frame_count - 1, 0)

    def _grow_frame_count(self, frame: int) -> None:
        if self.info is None:
            return
        need = int(frame) + 1
        if need <= self.info.frame_count:
            return
        self.info.frame_count = need
        if self.info.fps > 1e-3:
            self.info.duration = self.info.frame_count / self.info.fps
        self._player_sync_ui()

    def _sync_audio_position(self) -> None:
        if not self._audio_ok or self.info is None:
            return
        self._audio_player.setPosition(self._ms_from_frame(self._play_frame))

    def _start_audio(self) -> None:
        if not self._audio_ok or self.info is None:
            return
        self._apply_media_duration()
        self._audio_player.setPlaybackRate(float(self._play_rate))
        self._sync_audio_position()
        self._audio_player.play()

    def _stop_audio(self) -> None:
        if self._audio_player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._audio_player.pause()

    def _set_play_rate(self, rate: float) -> None:
        frame = self._play_frame
        was_playing = self._play_timer.isActive()
        if abs(self._play_rate - rate) < 1e-9:
            self._play_rate = 1.0
        else:
            self._play_rate = float(rate)
        self._refresh_rate_buttons()
        self._apply_play_timer_interval()
        self._audio_clock = False
        if self._audio_ok:
            self._audio_player.setPlaybackRate(float(self._play_rate))
            self._audio_player.setPosition(self._ms_from_frame(frame))
            if was_playing:
                self._audio_player.play()
        if self._play_frame != frame:
            self._show_frame(frame, sync_audio=False)
        QTimer.singleShot(300, self._resume_audio_clock)

    def _resume_audio_clock(self) -> None:
        self._audio_clock = True
        if self._play_timer.isActive() and self._audio_ok:
            self._sync_audio_position()

    def _refresh_rate_buttons(self) -> None:
        for rate, button in self._rate_buttons.items():
            active = abs(self._play_rate - rate) < 1e-9
            button.setStyleSheet(
                "background: #d7e4ff; border-color: #6f8fdb;" if active else ""
            )

    def _apply_play_timer_interval(self) -> None:
        if self.info is None:
            return
        base = 1000.0 / max(self.info.fps, 1.0)
        rate = max(self._play_rate, 1e-6)
        if rate < 1.0:
            interval = max(16, int(round(base / rate)))
        else:
            interval = max(16, int(round(base)))
        self._play_timer.setInterval(interval)

    def _dialog_dir(self, key: str) -> str:
        saved = str(self._settings.value(f"last_dir/{key}", "") or "")
        if saved and Path(saved).is_dir():
            return saved
        return str(Path.home())

    def _remember_dialog_dir(self, key: str, path: str | Path) -> None:
        target = Path(path)
        folder = target if target.is_dir() else target.parent
        if folder.is_dir():
            self._settings.setValue(f"last_dir/{key}", str(folder.resolve()))

    def open_video(self) -> None:
        exts = " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTENSIONS))
        path, _ = QFileDialog.getOpenFileName(
            self,
            "動画を開く",
            self._dialog_dir("video"),
            f"Video ({exts})",
        )
        if not path:
            return
        self._remember_dialog_dir("video", path)
        self._load_video(Path(path))

    def _load_video(self, path: Path) -> None:
        self._player_stop()
        self._release_cap()
        self._audio_ok = False
        self._audio_player.stop()
        try:
            info = read_video_info(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "動画を開けませんでした", str(exc))
            return
        self._video_path = path
        self.info = info
        self._play_frame = 0
        self._apply_play_timer_interval()
        self._set_player_enabled(True)
        if self._has_audio_output():
            self._audio_player.setSource(QUrl.fromLocalFile(str(path.resolve())))
            self._audio_player.setPosition(0)
        self._show_frame(0)

    def _player_sync_ui(self) -> None:
        last = 0
        if self.info is not None:
            last = max(self.info.frame_count - 1, 0)
        frame = max(0, min(int(self._play_frame), last))
        self._play_frame = frame
        self._play_syncing = True
        self.player_slider.setRange(0, last)
        self.player_slider.setValue(frame)
        self._play_syncing = False
        if self.info is None or self.info.fps <= 0:
            self.player_time.setText("—")
            return
        seconds = frame / self.info.fps
        self.player_time.setText(
            f"{format_timecode(seconds)}  /  {self.info.format_duration()}"
        )

    def _player_toggle(self) -> None:
        if self.info is None:
            return
        if self._play_timer.isActive():
            self._player_stop()
            return
        self._analyzing = False
        last = max(self.info.frame_count - 1, 0)
        if self._play_frame >= last:
            self._show_frame(0)
        self._start_audio()
        self._play_timer.start()
        self.player_play_btn.setText("停止")
        self._refresh_analyze_enabled()

    def _player_stop(self) -> None:
        was_analyzing = self._analyzing
        self._play_timer.stop()
        self._stop_audio()
        if was_analyzing:
            self._save_current_play()
        self._analyzing = False
        self._audio_clock = True
        self.player_play_btn.setText("再生")
        self._refresh_analyze_enabled()

    def _player_tick(self) -> None:
        if self.info is None:
            self._player_stop()
            return
        if (
            self._audio_clock
            and self._audio_ok
            and self._audio_player.playbackState()
            == QMediaPlayer.PlaybackState.PlayingState
        ):
            pos = int(self._audio_player.position())
            dur = int(self._audio_player.duration())
            nxt = self._frame_from_ms(pos)
            if dur > 0 and pos >= max(0, dur - 40):
                self._show_frame(nxt, sync_audio=False, allow_past_end=True)
                self._player_stop()
                return
            if not self._show_frame(nxt, sync_audio=False, allow_past_end=True):
                self._player_stop()
            return
        step = 1
        if self._play_rate >= 1.0:
            step = max(1, int(round(self._play_rate)))
        if self._analyzing:
            step = max(step, self._analyze_sample_step())
        nxt = self._play_frame + step
        if not self._show_frame(nxt, allow_past_end=True):
            self._player_stop()
            return
        if self._audio_ok and self._play_timer.isActive() and not self._audio_clock:
            self._sync_audio_position()

    def _player_step(self, delta: int) -> None:
        if self.info is None:
            return
        self._player_stop()
        self._show_frame(self._play_frame + int(delta))

    def _player_on_slider(self, value: int) -> None:
        if self._play_syncing or self.info is None:
            return
        self._player_stop()
        self._show_frame(int(value))

    def _keep_shown_frame(self, allow_past_end: bool, frame: int) -> bool:
        if allow_past_end and frame > self._play_frame:
            return True
        pixmap = self.preview.pixmap()
        return pixmap is not None and not pixmap.isNull()

    def _show_frame(
        self, frame: int, *, sync_audio: bool = True, allow_past_end: bool = False
    ) -> bool:
        if self.info is None:
            return False
        frame = max(0, int(frame))
        if not allow_past_end:
            frame = min(frame, self._last_frame())
        image = self._read_frame(frame)
        if image is None:
            if self._keep_shown_frame(allow_past_end, frame):
                return False
            self.preview.setText("この位置の画像を取得できませんでした")
            return False
        pixmap = self._to_preview_pixmap(image)
        if pixmap is None:
            if self._keep_shown_frame(allow_past_end, frame):
                return False
            self.preview.setText("この位置の画像を取得できませんでした")
            return False
        if frame >= self.info.frame_count:
            self._grow_frame_count(frame)
        self.preview.setPixmap(pixmap)
        self._play_frame = frame
        self._player_sync_ui()
        if sync_audio and not self._play_timer.isActive():
            self._sync_audio_position()
        if self._analyzing:
            self._analyze_frame(image)
        return True

    def _preview_target_size(self) -> tuple[int, int]:
        size = self.preview.size()
        tw = max(2, int(size.width()))
        th = max(2, int(size.height()))
        return tw, th

    def _to_preview_pixmap(self, image: np.ndarray) -> QPixmap | None:
        if image is None or image.size == 0:
            return None
        tw, th = self._preview_target_size()
        height, width = image.shape[:2]
        if width < 1 or height < 1:
            return None
        scale = min(tw / width, th / height, 1.0)
        out_w = max(1, int(width * scale))
        out_h = max(1, int(height * scale))
        if out_w != width or out_h != height:
            image = cv2.resize(image, (out_w, out_h), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        h, w, channels = rgb.shape
        qimage = QImage(rgb.data, w, h, channels * w, QImage.Format.Format_RGB888).copy()
        return QPixmap.fromImage(qimage)

    def _ensure_cap(self) -> bool:
        if self.info is None:
            return False
        if self._cap is not None and self._cap.isOpened():
            return True
        self._release_cap()
        self._cap = cv2.VideoCapture(str(self.info.path))
        if self._cap.isOpened():
            try:
                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
        self._cap_next = 0
        return bool(self._cap.isOpened())

    def _read_frame(self, frame_index: int):
        if self.info is None or not self._ensure_cap():
            return None
        target = max(0, int(frame_index))
        if target == self._cap_next:
            ok, image = self._cap.read()
            if ok and image is not None:
                self._cap_next = target + 1
                return image
        elif target > self._cap_next and (target - self._cap_next) <= 300:
            while self._cap_next < target:
                if not self._cap.grab():
                    break
                self._cap_next += 1
            else:
                ok, image = self._cap.retrieve()
                if ok and image is not None:
                    self._cap_next = target + 1
                    return image
        image = grab_frame(self._cap, target, self.info.fps)
        if image is None:
            self._release_cap()
            if not self._ensure_cap():
                return None
            image = grab_frame(self._cap, target, self.info.fps)
        if image is not None:
            self._cap_next = target + 1
        return image

    def _release_cap(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._cap_next = 0

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._apply_cell2_size()
        self._apply_cell6_lamp_size()
        self._fit_play_columns()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._player_stop()
        self._audio_player.stop()
        self._release_cap()
        event.accept()

    def _exe_estimate_text(self) -> str:
        raw = self._settings.value("exe_build_seconds", "")
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            seconds = 0.0
        if seconds <= 0:
            return "予想時間: まだ測っていません。"
        total = int(round(seconds))
        minutes, secs = divmod(total, 60)
        if minutes <= 0:
            return f"予想時間: 約 {secs} 秒（前回の所要時間）"
        return f"予想時間: 約 {minutes} 分 {secs} 秒（前回の所要時間）"

    def build_exe(self) -> None:
        if getattr(sys, "frozen", False):
            QMessageBox.information(
                self, ".exe 化", "すでに .exe から起動しています。"
            )
            return
        if self._exe_worker is not None and self._exe_worker.isRunning():
            return
        confirm = QMessageBox.question(
            self,
            ".exe 化",
            ".exe 化を始めますか？\n起動アイコンも自動で作ります。\n\n"
            + self._exe_estimate_text(),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        progress = QProgressDialog(
            ".exe を作成しています。しばらく待ってください。\n"
            + self._exe_estimate_text(),
            None,
            0,
            0,
            self,
        )
        progress.setWindowTitle(".exe 化")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.show()
        self._exe_progress = progress
        self._exe_btn.setEnabled(False)
        self._exe_build_started = time.monotonic()
        worker = ExeBuildWorker(self)
        self._exe_worker = worker
        worker.finished_ok.connect(self._on_exe_build_ok)
        worker.failed.connect(self._on_exe_build_failed)
        worker.start()

    def _remember_exe_build_seconds(self) -> None:
        started = getattr(self, "_exe_build_started", None)
        if started is None:
            return
        elapsed = max(1.0, time.monotonic() - float(started))
        self._settings.setValue("exe_build_seconds", elapsed)
        self._exe_build_started = None

    def _on_exe_build_ok(self, exe_path: object) -> None:
        self._remember_exe_build_seconds()
        self._finish_exe_build()
        path = Path(str(exe_path))
        try:
            self._create_launch_shortcut(
                target=path,
                arguments="",
                workdir=path.parent,
                quiet=True,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                ".exe 化",
                f".exe は作りました。\n{path}\n\n起動アイコンは作れませんでした。\n{exc}",
            )
            return
        QMessageBox.information(
            self,
            ".exe 化",
            f".exe を作り、起動アイコンも作りました。\n{path}",
        )

    def _on_exe_build_failed(self, message: str) -> None:
        self._exe_build_started = None
        self._finish_exe_build()
        QMessageBox.critical(self, ".exe 化", message or ".exe を作れませんでした")

    def _finish_exe_build(self) -> None:
        progress = getattr(self, "_exe_progress", None)
        if progress is not None:
            progress.close()
            self._exe_progress = None
        self._exe_btn.setEnabled(True)
        self._exe_worker = None

    def create_launch_shortcut(self) -> None:
        try:
            if EXE_PATH.is_file():
                self._create_launch_shortcut(
                    target=EXE_PATH,
                    arguments="",
                    workdir=EXE_PATH.parent,
                )
                return
            python = Path(sys.executable)
            pythonw = python.with_name("pythonw.exe")
            target = pythonw if pythonw.exists() else python
            script = APP_ROOT / "main.py"
            self._create_launch_shortcut(
                target=target,
                arguments=f'"{script}"',
                workdir=APP_ROOT,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "アイコンを作れませんでした", str(exc))

    def _create_launch_shortcut(
        self,
        *,
        target: Path,
        arguments: str,
        workdir: Path,
        quiet: bool = False,
    ) -> Path:
        desktop = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DesktopLocation
        )
        if not desktop:
            raise RuntimeError("デスクトップの場所が分かりませんでした。")
        lnk = Path(desktop) / f"{APP_NAME}.lnk"
        icon = APP_ROOT / "app.ico"
        if not icon.is_file() and target.suffix.lower() == ".exe":
            icon = target
        icon_path = icon if icon.is_file() or target.suffix.lower() == ".exe" else None

        def ps_quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        icon_line = ""
        if icon_path is not None:
            icon_line = f"$s.IconLocation = {ps_quote(str(icon_path) + ',0')}"
        command = (
            "$ws = New-Object -ComObject WScript.Shell\n"
            f"$s = $ws.CreateShortcut({ps_quote(str(lnk))})\n"
            f"$s.TargetPath = {ps_quote(str(target))}\n"
            f"$s.Arguments = {ps_quote(arguments)}\n"
            f"$s.WorkingDirectory = {ps_quote(str(workdir))}\n"
            "$s.WindowStyle = 1\n"
            f"$s.Description = {ps_quote(APP_NAME)}\n"
            f"{icon_line}\n"
            "$s.Save()\n"
        )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            creationflags=flags,
        )
        if result.returncode != 0 or not lnk.exists():
            err = (
                result.stderr or result.stdout or "ショートカットを作れませんでした"
            ).strip()
            raise RuntimeError(err)
        if not quiet:
            QMessageBox.information(
                self, "起動アイコン", f"デスクトップに作りました。\n{lnk}"
            )
        return lnk
